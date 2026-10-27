import { ParquetReader } from '@dsnp/parquetjs'
import { CompressionCodec } from '@dsnp/parquetjs/dist/gen-nodejs/parquet_types'
import { randomBytes } from 'node:crypto'

import { BLOCK_INDEX_COLUMNS, V4Index } from './index-columns'
import { indexRowsToParquet } from './parquet-writer'

async function describeFile(
    file: Buffer
): Promise<{ fields: string[]; rowGroups: number; codecs: unknown[]; rows: unknown[] }> {
    const reader = await ParquetReader.openBuffer(file)
    const fields = reader.schema.fieldList.map((field) =>
        [field.repetitionType, field.primitiveType ?? 'group', field.path.join('.'), field.originalType]
            .filter(Boolean)
            .join(' ')
    )
    const rowGroups = reader.metadata!.row_groups.length
    const codecs = reader.metadata!.row_groups.flatMap((group) =>
        group.columns.map((column) => column.meta_data?.codec)
    )
    const rows: unknown[] = []
    const cursor = reader.getCursor()
    for (let row = await cursor.next(); row; row = await cursor.next()) {
        rows.push(row)
    }
    await reader.close()
    return { fields, rowGroups, codecs, rows }
}

describe('indexRowsToParquet', () => {
    // The v4 index contract, shared with the recorder's JSON rows: name, order, nullability and type of each column.
    const SCHEMAS: Record<V4Index, string[]> = {
        images: [
            'REQUIRED INT64 team_id',
            'REQUIRED BYTE_ARRAY key_month UTF8',
            'REQUIRED BYTE_ARRAY image_ref UTF8',
            'REQUIRED BYTE_ARRAY pack_s3_key UTF8',
            'REQUIRED INT64 byte_start',
            'REQUIRED INT64 byte_end',
            'REQUIRED BYTE_ARRAY mime UTF8',
            'REQUIRED INT64 byte_size',
        ],
        blocks: [
            'REQUIRED INT64 team_id',
            'REQUIRED BYTE_ARRAY session_id UTF8',
            'REQUIRED BYTE_ARRAY key_month UTF8',
            'REQUIRED BYTE_ARRAY block_s3_key UTF8',
            'REQUIRED BYTE_ARRAY topic UTF8',
            'REQUIRED INT32 partition',
            'REQUIRED INT64 start_offset',
            'REQUIRED INT64 end_offset',
            'REQUIRED INT64 flush_end_offset',
            'REQUIRED INT32 flush_row_count',
            'REQUIRED INT32 flush_row_index',
            'REQUIRED BYTE_ARRAY flush_id UTF8',
            'REQUIRED INT64 flushed_at_ms',
            'REQUIRED INT64 block_byte_start',
            'REQUIRED INT64 block_byte_end',
            'OPTIONAL INT64 first_ts_ms',
            'OPTIONAL INT64 last_ts_ms',
            'REQUIRED INT64 event_count',
            'REQUIRED INT64 byte_size',
            'OPTIONAL BYTE_ARRAY snapshot_source UTF8',
            'OPTIONAL BYTE_ARRAY snapshot_library UTF8',
            'OPTIONAL BYTE_ARRAY host UTF8',
            'REQUIRED INT32 full_snapshots',
            'REQUIRED INT32 events_before_first_full_snapshot',
            'REQUIRED INT32 orphan_mutations',
            'REQUIRED INT32 decode_failures',
            'REQUIRED INT32 dom_nodes',
            'REQUIRED INT32 remote_stylesheets',
            'REQUIRED INT32 inline_stylesheets',
            'REQUIRED INT32 iframes',
            'REQUIRED INT32 canvases',
            'REQUIRED INT32 videos',
            'REQUIRED INT32 shadow_roots',
            'REQUIRED INT64 max_gap_ms',
            'REQUIRED INT64 active_ms',
            'REQUIRED INT64 dom_text_chars',
            'REQUIRED BOOLEAN cold_start',
            'REQUIRED BOOLEAN node_cap_reached',
            'REQUIRED BOOLEAN moments_truncated',
            'REQUIRED BOOLEAN touch_input',
            'REQUIRED INT32 clicks',
            'REQUIRED INT32 mouse_interactions',
            'REQUIRED INT32 rage_clicks',
            'REQUIRED INT32 dead_clicks',
            'REQUIRED INT32 keypresses',
            'REQUIRED INT32 scrolls',
            'REQUIRED INT32 mouse_moves',
            'REQUIRED INT32 touches',
            'REQUIRED INT32 touch_moves',
            'REQUIRED INT32 selections',
            'REQUIRED INT32 media_events',
            'REQUIRED INT32 viewport_resizes',
            'REQUIRED INT32 navigations',
            'REQUIRED INT32 console_errors',
            'REQUIRED INT32 console_warnings',
            'REQUIRED INT32 network_requests',
            'REQUIRED INT32 network_failures',
            'REQUIRED INT32 images_extracted',
            'REQUIRED INT32 images_inline',
            'REQUIRED INT32 image_urls',
            'REQUIRED INT64 image_bytes',
            'REQUIRED INT64 written_jsonl_bytes',
            'REQUIRED INT64 max_written_event_bytes',
            'OPTIONAL INT32 viewport_width',
            'OPTIONAL INT32 viewport_height',
            'OPTIONAL INT64 viewport_ts_ms',
            'REPEATED group moments',
            'REQUIRED BYTE_ARRAY moments.kind UTF8',
            'REQUIRED BYTE_ARRAY moments.window_id UTF8',
            'REQUIRED INT64 moments.ts_ms',
            'REQUIRED INT32 moments.event_index',
            'REPEATED BYTE_ARRAY url_fingerprints UTF8',
            'REPEATED BYTE_ARRAY window_ids UTF8',
            'OPTIONAL BYTE_ARRAY urls UTF8',
            'REQUIRED BOOLEAN urls_truncated',
        ],
    }

    it.each(['blocks', 'images'] as const)('writes the %s columns of the v4 index contract', async (index) => {
        const { fields } = await describeFile(await indexRowsToParquet(index, [], 1_000))
        expect(fields).toEqual(SCHEMAS[index])
    })

    it('reads back the values it writes, in row groups of the given size, with snappy on every column', async () => {
        const image = {
            team_id: 7,
            key_month: '2026-10',
            image_ref: 'image:v4:7:2026-10:abc',
            pack_s3_key: 'images/packs/dt=2026-10-15/7/1-0',
            byte_start: 0,
            byte_end: 99,
            mime: 'image/png',
            byte_size: 60,
        }
        const { rowGroups, codecs, rows } = await describeFile(
            await indexRowsToParquet('images', Array(5).fill(image), 2)
        )
        expect(rowGroups).toBe(3)
        expect(codecs).toEqual(Array(3 * 8).fill(CompressionCodec.SNAPPY))
        expect(rows).toEqual(Array(5).fill({ ...image, team_id: 7n, byte_start: 0n, byte_end: 99n, byte_size: 60n }))
    })

    const block = (moments: unknown[], windowIds: string[]): Record<string, unknown> =>
        Object.fromEntries(
            BLOCK_INDEX_COLUMNS.map((column) => [
                column.name,
                'repeated' in column
                    ? moments
                    : 'list' in column
                      ? windowIds
                      : column.optional
                        ? null
                        : column.type === 'UTF8'
                          ? 'x'
                          : column.type === 'BOOLEAN'
                            ? true
                            : 1,
            ])
        )

    it('writes a large sealed urls value with no copy of it in the statistics', async () => {
        const urls = randomBytes(768 * 1024).toString('base64')

        const file = await indexRowsToParquet('blocks', [{ ...block([], []), urls, urls_truncated: false }], 1_000)

        const { rows } = await describeFile(file)
        expect((rows as Record<string, unknown>[])[0]).toMatchObject({ urls, urls_truncated: false })
        // Snappy cannot shrink random base64, so the file is about one copy of the value.
        expect(file.length).toBeLessThan(urls.length * 1.1)
    })

    it('reads moments back as a list of structs and the string lists as lists', async () => {
        const moments = [
            { kind: 'click', window_id: 'w1', ts_ms: 1_000, event_index: 2 ** 31 - 1 },
            { kind: 'full_snapshot_undecoded', window_id: 'w2', ts_ms: 2_000, event_index: 0 },
        ]
        const { rows } = await describeFile(
            await indexRowsToParquet('blocks', [block(moments, ['w1', 'w2']), block([], [])], 1_000)
        )
        const read = rows as Record<string, unknown>[]
        expect(read.map((row) => [row.moments, row.url_fingerprints, row.window_ids])).toEqual([
            [moments.map((moment) => ({ ...moment, ts_ms: BigInt(moment.ts_ms) })), ['w1', 'w2'], ['w1', 'w2']],
            // parquetjs reads an empty repeated field as null; Arrow readers see an empty list.
            [null, null, null],
        ])
    })
})
