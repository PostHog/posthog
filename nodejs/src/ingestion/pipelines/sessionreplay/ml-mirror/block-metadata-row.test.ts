import { DateTime } from 'luxon'

import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { parseBlockUrl, toBlockMetadataRow } from './block-metadata-row'
import { PSEUDONYM_SESSION, PSEUDONYM_TEAM, pseudonymize } from './pseudonymize'

const SECRET = 'test-secret'

const block = (over: Partial<SessionBlockMetadata> = {}): SessionBlockMetadata => ({
    ...createNoopBlockMetadata('sess-1', 7),
    distinctId: 'user@example.com',
    blockUrl: 's3://ml-bucket/session_recordings/key-abc?range=bytes=100-250',
    startDateTime: DateTime.fromMillis(1_000),
    endDateTime: DateTime.fromMillis(2_000),
    eventCount: 5,
    messageCount: 3,
    urls: ['https://a/[redacted]'],
    ...over,
})

describe('ml-mirror block-metadata-row', () => {
    describe('parseBlockUrl', () => {
        it('splits the object key from the byte range', () => {
            expect(parseBlockUrl('s3://b/key?range=bytes=100-250')).toEqual({ key: 's3://b/key', start: 100, end: 250 })
        })

        it('returns null range when there is no range marker', () => {
            expect(parseBlockUrl('s3://b/key')).toEqual({ key: 's3://b/key', start: null, end: null })
        })
    })

    describe('toBlockMetadataRow', () => {
        it('pseudonymizes ids and never carries the raw values', () => {
            const row = toBlockMetadataRow(block(), SECRET)!
            expect(row.team_id).toBe(pseudonymize(SECRET, PSEUDONYM_TEAM, '7'))
            expect(row.session_id).toBe(pseudonymize(SECRET, PSEUDONYM_SESSION, 'sess-1'))
            expect(row.distinct_id).not.toContain('user@example.com')
            expect(row.session_id).not.toBe('sess-1')
        })

        it('maps block fields and the parsed byte range', () => {
            const row = toBlockMetadataRow(block(), SECRET)!
            expect(row).toMatchObject({
                block_s3_key: 's3://ml-bucket/session_recordings/key-abc',
                block_byte_start: 100,
                block_byte_end: 250,
                first_ts_ms: 1_000,
                last_ts_ms: 2_000,
                event_count: 5,
                message_count: 3,
                urls: ['https://a/[redacted]'],
            })
        })

        it.each([
            ['a deletion marker', block({ isDeleted: true })],
            ['a block with no url', block({ blockUrl: null })],
        ])('returns null for %s', (_label, b) => {
            expect(toBlockMetadataRow(b, SECRET)).toBeNull()
        })
    })
})
