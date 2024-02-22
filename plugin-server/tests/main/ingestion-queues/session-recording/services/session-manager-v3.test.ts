import { Upload } from '@aws-sdk/lib-storage'
import fs from 'fs/promises'
import { DateTime, Settings } from 'luxon'
import path from 'path'

import { defaultConfig } from '../../../../../src/config/config'
import { SessionManagerV3 } from '../../../../../src/main/ingestion-queues/session-recording/services/session-manager-v3'
import { now } from '../../../../../src/main/ingestion-queues/session-recording/utils'
import { createIncomingRecordingMessage } from '../fixtures'

// class MockStream {
//     write = jest.fn(() => true)
//     close = jest.fn((cb) => cb?.())
//     end = jest.fn((cb) => cb?.())
//     on = jest.fn()
//     once = jest.fn((val, cb) => cb?.())
// }

// jest.mock('fs', () => {
//     return {
//         ...jest.requireActual('fs'),
//         writeFileSync: jest.fn(),
//         createReadStream: jest.fn(() => new MockStream()),
//         createWriteStream: jest.fn(() => new MockStream()),
//     }
// })

// jest.mock('stream/promises', () => {
//     return {
//         ...jest.requireActual('stream/promises'),
//         pipeline: jest.fn(
//             () =>
//                 new Promise<void>((_res) => {
//                     // do nothing
//                 })
//         ),
//     }
// })

// jest.mock('stream', () => {
//     return {
//         ...jest.requireActual('stream'),
//         PassThrough: jest.fn(() => new MockStream()),
//     }
// })

jest.mock('@aws-sdk/lib-storage', () => {
    const mockUpload = jest.fn().mockImplementation(() => {
        return {
            abort: jest.fn().mockResolvedValue(undefined),
            done: jest.fn().mockResolvedValue(undefined),
        }
    })

    return {
        __esModule: true,
        Upload: mockUpload,
    }
})

// jest.mock('fs/promises', () => {
//     return {
//         ...jest.requireActual('fs/promises'),
//         unlink: jest.fn().mockResolvedValue(undefined),
//     }
// })

const tmpDir = path.join(__dirname, '../../../../../.tmp/test_session_recordings')

describe('session-manager', () => {
    jest.setTimeout(1000)
    let sessionManager: SessionManagerV3
    const mockS3Client: any = {
        send: jest.fn(),
    }

    const createSessionManager = async (): Promise<SessionManagerV3> => {
        return await SessionManagerV3.create(defaultConfig, mockS3Client, {
            sessionId: 'session_id_1',
            teamId: 1,
            partition: 1,
            dir: path.join(tmpDir, '1'),
        })
    }

    const flushThreshold = defaultConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000

    beforeEach(async () => {
        // it's always May 25
        Settings.now = () => new Date(2018, 4, 25).valueOf()

        await fs.rmdir(tmpDir, { recursive: true })

        sessionManager = await createSessionManager()
    })

    afterEach(async () => {
        await sessionManager?.stop()
        // it's no longer always May 25
        Settings.now = () => new Date().valueOf()
    })

    it('adds a message', async () => {
        const timestamp = now()
        const event = createIncomingRecordingMessage({
            events: [
                { timestamp: timestamp, type: 4, data: { href: 'http://localhost:3001/' } },
                { timestamp: timestamp + 1000, type: 4, data: { href: 'http://localhost:3001/' } },
            ],
        })

        await sessionManager.add(event)

        expect(sessionManager.buffer?.context).toEqual({
            sizeEstimate: 193,
            count: 1,
            eventsRange: { firstTimestamp: 1527202800000, lastTimestamp: 1527202801000 },
            createdAt: 1527202800000,
        })

        const stats = await fs.stat(path.join(tmpDir, '1', 'buffer.jsonl.gz'))
        expect(stats.size).toBeGreaterThan(0)
    })

    it('does not flush if it has received a message recently', async () => {
        const now = DateTime.now()

        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now,
            } as any,
        })

        await sessionManager.add(event)
        await sessionManager.flush()

        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual(['buffer.jsonl.gz', 'metadata.json'])
    })

    it('does flush if the stored file is older than the threshold', async () => {
        const firstTimestamp = 1700000000000
        const lastTimestamp = 1700000000000 + 4000

        const eventOne = createIncomingRecordingMessage({
            events: [{ timestamp: firstTimestamp, type: 4, data: { href: 'http://localhost:3001/' } }],
        })
        const eventTwo = createIncomingRecordingMessage({
            events: [{ timestamp: lastTimestamp, type: 4, data: { href: 'http://localhost:3001/' } }],
        })

        await sessionManager.add(eventOne)
        await sessionManager.add(eventTwo)

        sessionManager.buffer!.context.createdAt = now() - flushThreshold - 1

        await sessionManager.flush()

        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual([])

        // as a proxy for flush having been called or not
        const mockUploadCalls = (Upload as unknown as jest.Mock).mock.calls
        expect(mockUploadCalls.length).toBe(1)
        expect(mockUploadCalls[0].length).toBe(1)
        expect(mockUploadCalls[0][0]).toEqual(
            expect.objectContaining({
                params: expect.objectContaining({
                    Key: `session_recordings/team_id/1/session_id/session_id_1/data/${firstTimestamp}-${lastTimestamp}.jsonl.gz`,
                }),
            })
        )
    })

    it('has a fixed jitter based on the serverConfig', async () => {
        const minJitter = 1 - defaultConfig.SESSION_RECORDING_BUFFER_AGE_JITTER
        for (const _ of Array(100).keys()) {
            const sm = await createSessionManager()
            expect(sm.flushJitterMultiplier).toBeGreaterThanOrEqual(minJitter)
            expect(sm.flushJitterMultiplier).toBeLessThanOrEqual(1)
        }
    })

    it('not remove files when stopped', async () => {
        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual([])
        await sessionManager.add(createIncomingRecordingMessage())
        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual(['buffer.jsonl.gz', 'metadata.json'])
        await sessionManager.stop()
        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual(['buffer.jsonl.gz', 'metadata.json'])
    })

    it('removes the directly when stopped after fully flushed', async () => {
        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual([])
        await sessionManager.add(createIncomingRecordingMessage())
        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual(['buffer.jsonl.gz', 'metadata.json'])
        await sessionManager.flush(true)
        expect(await fs.readdir(path.join(tmpDir, '1'))).toEqual([])
        await sessionManager.stop()
        ;(sessionManager as any) = undefined // Stop the afterEach from failing

        await expect(fs.stat(path.join(tmpDir, '1'))).rejects.toThrowError('ENOENT: no such file or directory')
    })
})
