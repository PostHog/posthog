import { parseBlockMetadataMessages } from './block-metadata-message'
import { MlBlockMetadataRow } from './block-metadata-row'

const fullRow = (over: Partial<MlBlockMetadataRow> = {}): MlBlockMetadataRow => ({
    session_id: 's1',
    team_id: 't1',
    distinct_id: 'd1',
    block_url: 's3://b/k?range=bytes=0-9',
    block_s3_key: 's3://b/k',
    block_byte_start: 0,
    block_byte_end: 9,
    block_length: 10,
    first_ts_ms: 1_000,
    last_ts_ms: 2_000,
    event_count: 3,
    message_count: 1,
    click_count: 0,
    keypress_count: 0,
    mouse_activity_count: 0,
    active_milliseconds: 0,
    console_log_count: 0,
    console_warn_count: 0,
    console_error_count: 0,
    size: 100,
    first_url: null,
    urls: [],
    snapshot_source: null,
    snapshot_library: null,
    retention_period_days: null,
    ...over,
})

const msg = (value: unknown): { value: Buffer | null } => ({
    value: value === null ? null : Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)),
})

describe('parseBlockMetadataMessages', () => {
    it('parses well-formed rows and preserves their fields', () => {
        const rows = parseBlockMetadataMessages([msg(fullRow({ session_id: 'a', event_count: 3 })), msg(fullRow())])
        expect(rows).toHaveLength(2)
        expect(rows[0]).toMatchObject({ session_id: 'a', event_count: 3 })
    })

    it('skips null values and malformed JSON without throwing', () => {
        const rows = parseBlockMetadataMessages([msg(null), msg('not json{'), msg(fullRow({ session_id: 'ok' }))])
        expect(rows).toHaveLength(1)
        expect(rows[0].session_id).toBe('ok')
    })

    it('skips shape-invalid rows (poison-pill guard) without throwing', () => {
        const rows = parseBlockMetadataMessages([
            msg({ session_id: 'a', event_count: 3 }), // missing required numeric fields + urls
            msg(fullRow({ event_count: 'oops' as unknown as number })), // wrong type
            msg(fullRow({ urls: 'not-an-array' as unknown as string[] })),
            msg(fullRow({ session_id: 'good' })),
        ])
        expect(rows).toHaveLength(1)
        expect(rows[0].session_id).toBe('good')
    })
})
