import { parseBlockMetadataMessages } from './block-metadata-message'
import { MlBlockMetadataRow } from './block-metadata-row'

const fullRow = (over: Partial<MlBlockMetadataRow> = {}): MlBlockMetadataRow => ({
    session_id: 's1',
    team_id: 't1',
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
        const rows = parseBlockMetadataMessages([
            msg(fullRow({ session_id: 'a', event_count: 3, team_id: '42', format_version: 2 })),
            msg({ ...fullRow(), distinct_id: 'legacy-user', distinctId: 'unexpected-user' }),
        ])
        expect(rows).toHaveLength(2)
        expect(rows[1]).toEqual(fullRow())
        expect(rows[0]).toMatchObject({ session_id: 'a', event_count: 3, team_id: '42', format_version: 2 })
    })

    it('skips null values and malformed JSON without throwing', () => {
        const rows = parseBlockMetadataMessages([msg(null), msg('not json{'), msg(fullRow({ session_id: 'ok' }))])
        expect(rows).toHaveLength(1)
        expect(rows[0].session_id).toBe('ok')
    })

    it('skips shape-invalid rows (poison-pill guard) without throwing', () => {
        const rows = parseBlockMetadataMessages([
            msg({ session_id: 'a', event_count: 3, team_id: '42', format_version: 2 }), // missing required numeric fields + urls
            msg(fullRow({ event_count: 'oops' as unknown as number })), // wrong type
            msg(fullRow({ urls: 'not-an-array' as unknown as string[] })),
            msg(fullRow({ block_byte_start: 'oops' as unknown as number })), // optional and repeated values the writer cannot encode
            msg(fullRow({ first_url: 5 as unknown as string })),
            msg(fullRow({ urls: [1] as unknown as string[] })),
            msg(fullRow({ event_count: 2 ** 31 })), // numbers outside the range of their Parquet type
            msg(fullRow({ retention_period_days: 2 ** 31 })),
            msg(fullRow({ block_length: 2 ** 63 })),
            msg(fullRow({ first_ts_ms: 9e15 })),
            msg(fullRow({ click_count: 0.5 })), // fractions that an integer column would truncate
            msg(fullRow({ block_length: 1.5 })),
            msg(fullRow({ format_version: 2, team_id: 'a'.repeat(32) })),
            msg(fullRow({ format_version: 2, team_id: '9007199254740992' })),
            msg({ ...fullRow(), format_version: 3 }),
            msg(fullRow({ session_id: 'good' })),
        ])
        expect(rows).toHaveLength(1)
        expect(rows[0].session_id).toBe('good')
    })
})
