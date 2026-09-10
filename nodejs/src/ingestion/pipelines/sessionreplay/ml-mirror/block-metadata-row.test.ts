import { DateTime } from 'luxon'

import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { parseBlockUrl, toBlockMetadataRow } from './block-metadata-row'

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
    it.each([
        ['018bcfe5-6800-7000-8000-000000000001', 1_700_000_000_000],
        ['018BCFE5-6800-7000-8000-000000000001', 1_700_000_000_000],
        ['018bcfe5-6800-4000-8000-000000000001', undefined],
        ['018bcfe5-6800-7000-0000-000000000001', undefined],
        ['legacy-session', undefined],
    ])('derives the session partition and preserves session ID %s', (sessionId, expected) => {
        const result = toBlockMetadataRow(block({ sessionId: String(sessionId) }))!
        expect(result.session_start_ts_ms).toBe(expected)
        expect(result.session_id).toBe(sessionId)
    })

    describe('parseBlockUrl', () => {
        it('splits the object key from the byte range', () => {
            expect(parseBlockUrl('s3://b/key?range=bytes=100-250')).toEqual({ key: 's3://b/key', start: 100, end: 250 })
        })

        it('returns null range when there is no range marker', () => {
            expect(parseBlockUrl('s3://b/key')).toEqual({ key: 's3://b/key', start: null, end: null })
        })
    })

    describe('toBlockMetadataRow', () => {
        it('preserves raw team, session, and distinct IDs', () => {
            const row = toBlockMetadataRow(block())!
            expect(row.team_id).toBe('7')
            expect(row.format_version).toBe(2)
            expect(row.session_id).toBe('sess-1')
            expect(row.distinct_id).toBe('user@example.com')
        })

        it('maps block fields and the parsed byte range', () => {
            const row = toBlockMetadataRow(block())!
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
            expect(toBlockMetadataRow(b)).toBeNull()
        })
    })
})
