import { PutObjectCommandInput, S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'

import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'

const row = (sessionId: string, teamId: string): MlBlockMetadataRow => ({
    session_id: sessionId,
    team_id: teamId,
    distinct_id: 'did-pseudo',
    block_url: `s3://ml-bucket/key-${sessionId}?range=bytes=0-9`,
    block_s3_key: `s3://ml-bucket/key-${sessionId}`,
    block_byte_start: 0,
    block_byte_end: 9,
    block_length: 10,
    first_ts_ms: 1_000,
    last_ts_ms: 2_000,
    event_count: 4,
    message_count: 2,
    click_count: 1,
    keypress_count: 0,
    mouse_activity_count: 1,
    active_milliseconds: 500,
    console_log_count: 0,
    console_warn_count: 0,
    console_error_count: 0,
    size: 100,
    first_url: 'https://x/[redacted]',
    urls: ['https://x/[redacted]'],
    snapshot_source: 'web',
    snapshot_library: 'web',
    retention_period_days: 30,
})

async function readRows(body: PutObjectCommandInput['Body']): Promise<Record<string, any>[]> {
    const reader = await ParquetReader.openBuffer(body as Buffer)
    const cursor = reader.getCursor()
    const rows: Record<string, any>[] = []
    let r: unknown
    while ((r = await cursor.next())) {
        rows.push(r as Record<string, any>)
    }
    await reader.close()
    return rows
}

describe('BlockMetadataParquetStore', () => {
    let puts: PutObjectCommandInput[]
    let s3: S3Client

    beforeEach(() => {
        puts = []
        s3 = {
            send: jest.fn((cmd: { input: PutObjectCommandInput }) => {
                puts.push(cmd.input)
                return Promise.resolve({})
            }),
        } as unknown as S3Client
    })

    it('writes one dt-partitioned Parquet object that round-trips', async () => {
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        await store.write([row('s1', 't1'), row('s2', 't1')])

        expect(puts).toHaveLength(1)
        expect(puts[0].Bucket).toBe('ml-bucket')
        expect(puts[0].Key).toMatch(/^block-metadata\/dt=\d{4}-\d{2}-\d{2}\/part-pod-1-\d+-\d+\.parquet$/)

        const rows = await readRows(puts[0].Body)
        expect(rows).toHaveLength(2)
        expect(Number(rows[0].block_byte_end)).toBe(9)
        expect(rows[0].snapshot_source).toBe('web')
    })

    it('indexes cross-block pairs by session start day and preserves window and fractional timestamps', async () => {
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        const start = Date.parse('2025-01-01T23:59:00Z')
        const snapshotTimestamp = start + 60_000.5
        const full = {
            ...row('s1', 't1'),
            session_start_ts_ms: start,
            first_ts_ms: snapshotTimestamp,
            last_ts_ms: snapshotTimestamp,
            replay_index_entries: [
                { kind: 'full_snapshot' as const, windowId: 'w1', eventTimestamp: snapshotTimestamp, eventIndex: 0 },
                {
                    kind: 'page' as const,
                    windowId: 'w1',
                    eventTimestamp: snapshotTimestamp,
                    eventIndex: 1,
                    url: 'https://example.com/[redacted]',
                },
            ],
        }
        const label = {
            ...full,
            block_s3_key: 's3://ml-bucket/other-block',
            replay_index_entries: [
                {
                    kind: 'json_ld' as const,
                    windowId: 'w1',
                    eventTimestamp: snapshotTimestamp,
                    eventIndex: 2,
                    fullSnapshotTimestamp: snapshotTimestamp,
                    rootTypes: ['Product'],
                },
            ],
        }
        await store.write([label])
        await store.write([full])
        const indexPuts = puts.filter((put) => put.Key!.includes('-replay-index/'))
        expect(indexPuts).toHaveLength(3)
        for (const put of indexPuts) {
            expect(put.Key).toContain('/session_start_date=2025-01-01/')
        }
        const labels = await readRows(indexPuts.find((put) => put.Key!.includes('kind=json_ld'))!.Body)
        const snapshots = await readRows(indexPuts.find((put) => put.Key!.includes('kind=full_snapshot'))!.Body)
        expect(labels[0]).toMatchObject({
            team_id: 't1',
            session_id: 's1',
            window_id: 'w1',
            event_index: 2,
            full_snapshot_ts_ms: snapshots[0].event_ts_ms,
            root_types: ['Product'],
            block_s3_key: 's3://ml-bucket/other-block',
            block_byte_start: 0,
            block_byte_end: 9,
        })
        expect(snapshots[0].event_ts_ms).toBe(snapshotTimestamp)
        const pages = await readRows(indexPuts.find((put) => put.Key!.includes('kind=page'))!.Body)
        expect(pages[0].url).toBe('https://example.com/[redacted]')
    })

    it('propagates index upload failures so Kafka offsets cannot advance', async () => {
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        jest.mocked(s3.send).mockImplementationOnce(() => Promise.reject(new Error('index unavailable')))
        await expect(
            store.write([
                {
                    ...row('s1', 't1'),
                    session_start_ts_ms: 1000,
                    replay_index_entries: [
                        { kind: 'full_snapshot', windowId: 'w1', eventTimestamp: 1000, eventIndex: 0 },
                    ],
                },
            ])
        ).rejects.toThrow('index unavailable')
    })

    it.each([
        { session_start_ts_ms: undefined },
        { session_start_ts_ms: 3000 },
        { session_start_ts_ms: 1, last_ts_ms: 8 * 86_400_000 },
        { replay_index_entries: [{ kind: 'full_snapshot', windowId: 'w1', eventTimestamp: 1000, eventIndex: 99 }] },
        {
            replay_index_entries: [
                {
                    kind: 'json_ld',
                    windowId: 'w1',
                    eventTimestamp: 1000,
                    eventIndex: 0,
                    fullSnapshotTimestamp: 'invalid',
                },
            ],
        },
    ])('keeps block metadata when index fields are unusable: %j', async (override) => {
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        await store.write([
            {
                ...row('s1', 't1'),
                session_start_ts_ms: 1000,
                replay_index_entries: [{ kind: 'full_snapshot', windowId: 'w1', eventTimestamp: 1000, eventIndex: 0 }],
                ...override,
            } as MlBlockMetadataRow,
        ])
        expect(puts).toHaveLength(1)
        expect(puts[0].Key).toMatch(/^block-metadata\/dt=/)
    })

    it('sorts rows by (team_id, session_id)', async () => {
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        await store.write([row('s9', 't3'), row('s1', 't1'), row('s5', 't2'), row('s2', 't1')])
        const rows = await readRows(puts[0].Body)
        const keys = rows.map((r) => `${r.team_id}|${r.session_id}`)
        expect(keys).toEqual([...keys].sort())
    })

    it('writes nothing for an empty batch', async () => {
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        await store.write([])
        expect(puts).toHaveLength(0)
    })

    it('propagates upload failures so the caller can replay from Kafka', async () => {
        s3 = { send: jest.fn(() => Promise.reject(new Error('s3 down'))) } as unknown as S3Client
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        await expect(store.write([row('s1', 't1')])).rejects.toThrow('s3 down')
    })
})
