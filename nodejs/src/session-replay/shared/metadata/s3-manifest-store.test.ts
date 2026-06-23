import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { DateTime } from 'luxon'

import { parseJSON } from '../../../utils/json-parse'
import { S3ManifestStore } from './s3-manifest-store'
import { SessionBlockMetadata } from './session-block-metadata'

function block(overrides: Partial<SessionBlockMetadata> = {}): SessionBlockMetadata {
    return {
        sessionId: 'session123',
        teamId: 7,
        distinctId: 'user1',
        batchId: 'batch-abc',
        blockLength: 100,
        startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z', { zone: 'utc' }),
        endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z', { zone: 'utc' }),
        blockUrl: 's3://ml-bucket/rrweb/file1?range=bytes=0-99',
        firstUrl: 'https://example.com',
        urls: ['https://example.com'],
        eventCount: 25,
        clickCount: 5,
        keypressCount: 10,
        mouseActivityCount: 15,
        activeMilliseconds: 2000,
        consoleLogCount: 3,
        consoleWarnCount: 2,
        consoleErrorCount: 1,
        size: 1024,
        messageCount: 50,
        snapshotSource: 'web',
        snapshotLibrary: 'rrweb@1.0.0',
        retentionPeriodDays: null,
        isDeleted: false,
        ...overrides,
    }
}

describe('S3ManifestStore', () => {
    let s3Client: jest.Mocked<S3Client>
    let store: S3ManifestStore

    beforeEach(() => {
        s3Client = { send: jest.fn().mockResolvedValue({}) } as unknown as jest.Mocked<S3Client>
        store = new S3ManifestStore(s3Client, 'ml-bucket', 'rrweb')
    })

    it('writes one JSONL row per addressable block under <prefix>/manifests/<batchId>.jsonl', async () => {
        await store.writeManifest([
            block({ sessionId: 'a', teamId: 7, blockUrl: 's3://ml-bucket/rrweb/f1?range=bytes=0-99' }),
            block({ sessionId: 'b', teamId: 12, blockUrl: 's3://ml-bucket/rrweb/f1?range=bytes=100-250' }),
        ])

        expect(s3Client.send).toHaveBeenCalledTimes(1)
        const command = s3Client.send.mock.calls[0][0] as PutObjectCommand
        expect(command.input.Bucket).toBe('ml-bucket')
        expect(command.input.Key).toBe('rrweb/manifests/batch-abc.jsonl')

        const lines = (command.input.Body as string).trim().split('\n')
        expect(lines).toHaveLength(2)
        expect(parseJSON(lines[0])).toMatchObject({
            session_id: 'a',
            team_id: 7,
            block_url: 's3://ml-bucket/rrweb/f1?range=bytes=0-99',
            start_timestamp: '2025-01-01T10:00:00.000Z',
        })
        expect(parseJSON(lines[1])).toMatchObject({ session_id: 'b', team_id: 12 })
    })

    it('skips blocks with a null blockUrl (deletion markers / empty sessions)', async () => {
        await store.writeManifest([
            block({ sessionId: 'a', blockUrl: 's3://ml-bucket/rrweb/f1?range=bytes=0-99' }),
            block({ sessionId: 'deleted', blockUrl: null }),
        ])

        const command = s3Client.send.mock.calls[0][0] as PutObjectCommand
        const lines = (command.input.Body as string).trim().split('\n')
        expect(lines).toHaveLength(1)
        expect(parseJSON(lines[0]).session_id).toBe('a')
    })

    it('writes nothing when no block is addressable', async () => {
        await store.writeManifest([block({ blockUrl: null })])
        expect(s3Client.send).not.toHaveBeenCalled()
    })

    it('writes nothing for an empty batch', async () => {
        await store.writeManifest([])
        expect(s3Client.send).not.toHaveBeenCalled()
    })
})
