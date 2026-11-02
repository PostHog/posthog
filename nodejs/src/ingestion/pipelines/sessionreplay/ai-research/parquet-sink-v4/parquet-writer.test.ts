import { ParquetReader } from '@dsnp/parquetjs'
import { CompressionCodec, ConvertedType } from '@dsnp/parquetjs/dist/gen-nodejs/parquet_types'
import { randomBytes } from 'node:crypto'

import { BLOCK_INDEX_COLUMNS, V4Index } from './index-columns'
import { indexRowsToParquet } from './parquet-writer'

const CONVERTED_TYPE_NAMES: Record<number, string> = Object.fromEntries(
    Object.entries(ConvertedType).map(([name, value]) => [value, name])
)

async function describeFile(
    file: Buffer
): Promise<{ fields: string[]; rowGroups: number; codecs: unknown[]; rows: unknown[] }> {
    const reader = await ParquetReader.openBuffer(file)
    // parquetjs's reader drops a group's LIST annotation, so annotations come from the footer, which lists fields in fieldList order.
    const footer = reader.metadata!.schema.slice(1)
    const fields = reader.schema.fieldList.map((field, index) =>
        [
            field.repetitionType,
            field.primitiveType ?? 'group',
            field.path.join('.'),
            CONVERTED_TYPE_NAMES[footer[index].converted_type!],
        ]
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
            'REQUIRED group moments LIST',
            'REPEATED group moments.list',
            'REQUIRED group moments.list.element',
            'REQUIRED BYTE_ARRAY moments.list.element.kind UTF8',
            'REQUIRED BYTE_ARRAY moments.list.element.window_id UTF8',
            'REQUIRED INT64 moments.list.element.ts_ms',
            'REQUIRED INT32 moments.list.element.event_index',
            'REPEATED BYTE_ARRAY url_fingerprints UTF8',
            'REPEATED BYTE_ARRAY window_ids UTF8',
            'OPTIONAL BYTE_ARRAY urls UTF8',
            'REQUIRED BOOLEAN urls_truncated',
            'OPTIONAL INT32 surfacing_event_count',
            'OPTIONAL INT32 surfacing_click_count',
            'OPTIONAL INT32 surfacing_keypress_count',
            'OPTIONAL INT32 surfacing_mouse_activity_count',
            'OPTIONAL INT32 surfacing_rage_click_count',
            'OPTIONAL INT32 surfacing_dead_click_count',
            'OPTIONAL INT32 surfacing_quick_back_count',
            'OPTIONAL INT32 surfacing_page_visit_count',
            'OPTIONAL INT32 surfacing_text_selection_count',
            'OPTIONAL INT32 surfacing_scroll_event_count',
            'OPTIONAL INT32 surfacing_console_error_count',
            'OPTIONAL INT32 surfacing_console_error_after_click_count',
            'OPTIONAL INT32 surfacing_console_warn_count',
            'OPTIONAL INT32 surfacing_network_request_count',
            'OPTIONAL INT32 surfacing_network_failed_request_count',
            'OPTIONAL INT32 surfacing_network_4xx_count',
            'OPTIONAL INT32 surfacing_network_5xx_count',
            'OPTIONAL INT32 surfacing_network_request_duration_count',
            'OPTIONAL INT32 surfacing_mouse_position_count',
            'OPTIONAL INT32 surfacing_mouse_direction_change_count',
            'OPTIONAL INT32 surfacing_mouse_velocity_count',
            'OPTIONAL INT32 surfacing_scroll_direction_reversal_count',
            'OPTIONAL INT32 surfacing_rapid_scroll_reversal_count',
            'OPTIONAL INT32 surfacing_scroll_to_top_count',
            'OPTIONAL INT32 surfacing_inter_action_gap_count',
            'OPTIONAL INT32 surfacing_long_idle_gap_count',
            'OPTIONAL INT32 surfacing_backspace_count',
            'OPTIONAL INT32 surfacing_mutation_count',
            'OPTIONAL INT32 surfacing_viewport_resize_count',
            'OPTIONAL INT32 surfacing_touch_event_count',
            'OPTIONAL INT32 surfacing_selection_copy_count',
            'OPTIONAL INT32 surfacing_login_path_visit_count',
            'OPTIONAL INT32 surfacing_signup_path_visit_count',
            'OPTIONAL INT32 surfacing_checkout_path_visit_count',
            'OPTIONAL INT32 surfacing_cart_path_visit_count',
            'OPTIONAL INT32 surfacing_billing_path_visit_count',
            'OPTIONAL INT32 surfacing_settings_path_visit_count',
            'OPTIONAL INT32 surfacing_account_path_visit_count',
            'OPTIONAL INT32 surfacing_error_path_visit_count',
            'OPTIONAL INT32 surfacing_not_found_path_visit_count',
            'OPTIONAL INT32 surfacing_admin_path_visit_count',
            'OPTIONAL INT32 surfacing_dashboard_path_visit_count',
            'OPTIONAL INT32 surfacing_onboarding_path_visit_count',
            'OPTIONAL INT32 surfacing_cancel_path_visit_count',
            'OPTIONAL INT32 surfacing_refund_path_visit_count',
            'OPTIONAL INT64 surfacing_mouse_sum_x_millipx',
            'OPTIONAL INT64 surfacing_mouse_sum_x_squared_px2',
            'OPTIONAL INT64 surfacing_mouse_sum_y_millipx',
            'OPTIONAL INT64 surfacing_mouse_sum_y_squared_px2',
            'OPTIONAL INT64 surfacing_mouse_distance_traveled_millipx',
            'OPTIONAL INT64 surfacing_mouse_velocity_sum_px_per_s',
            'OPTIONAL INT64 surfacing_mouse_velocity_sum_of_squares_px2_per_s2',
            'OPTIONAL INT64 surfacing_total_scroll_magnitude_millipx',
            'OPTIONAL INT64 surfacing_inter_action_gap_sum_ms',
            'OPTIONAL INT64 surfacing_inter_action_gap_sum_of_squares_ms2',
            'OPTIONAL INT64 surfacing_network_request_duration_sum_us',
            'OPTIONAL INT64 surfacing_network_request_duration_sum_of_squares_ms2',
            'OPTIONAL INT64 surfacing_max_scroll_y_millipx',
            'OPTIONAL INT64 surfacing_max_idle_gap_ms',
            'OPTIONAL group surfacing_visited_url_fingerprints LIST',
            'REPEATED group surfacing_visited_url_fingerprints.list',
            'REQUIRED BYTE_ARRAY surfacing_visited_url_fingerprints.list.element UTF8',
            'OPTIONAL group surfacing_click_target_ids LIST',
            'REPEATED group surfacing_click_target_ids.list',
            'REQUIRED INT64 surfacing_click_target_ids.list.element',
            'OPTIONAL group surfacing_form_field_ids LIST',
            'REPEATED group surfacing_form_field_ids.list',
            'REQUIRED INT64 surfacing_form_field_ids.list.element',
        ],
    }

    it.each(['blocks', 'images'] as const)('writes the %s columns of the v4 index contract', async (index) => {
        const { fields } = await describeFile(await indexRowsToParquet(index, [], 1_000))
        expect(fields).toEqual(SCHEMAS[index])
    })

    it('reads back the values it writes, in row groups of the given size, with zstd on every column', async () => {
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
        expect(codecs).toEqual(Array(3 * 8).fill(CompressionCodec.ZSTD))
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
                      : 'elements' in column || column.optional
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
        // Zstd shrinks random base64 by about a quarter, so a second copy in the statistics would break this bound.
        expect(file.length).toBeLessThan(urls.length * 1.1)
    })

    it('writes blocks in (team_id, session_id, first_ts_ms) order, with a null first_ts_ms last', async () => {
        const at = (team_id: number, session_id: string, first_ts_ms: number | null): Record<string, unknown> => ({
            ...block([], []),
            team_id,
            session_id,
            first_ts_ms,
        })
        const arrival = [at(10, 'a', 1), at(2, 'b', null), at(2, 'b', 30), at(2, 'a', 5), at(2, 'b', 4)]

        const { rows } = await describeFile(await indexRowsToParquet('blocks', arrival, 1_000))

        expect(
            (rows as Record<string, unknown>[]).map((row) => [row.team_id, row.session_id, row.first_ts_ms ?? null])
        ).toEqual([
            [2n, 'a', 5n],
            [2n, 'b', 4n],
            [2n, 'b', 30n],
            [2n, 'b', null],
            [10n, 'a', 1n],
        ])
    })

    it('reads the surfacing lists back as 3-level lists, and a row without them as null', async () => {
        const surfacing = {
            surfacing_click_count: 3,
            surfacing_mouse_sum_x_millipx: -(2 ** 53 - 1),
            surfacing_visited_url_fingerprints: ['0f1e2d3c4b5a6978', 'b08517cee3ff5ecc'],
            surfacing_click_target_ids: [-1, 2 ** 53 - 1],
            surfacing_form_field_ids: [],
        }
        const { rows } = await describeFile(
            await indexRowsToParquet('blocks', [{ ...block([], []), ...surfacing }, block([], [])], 1_000)
        )
        const read = (rows as Record<string, unknown>[]).map((row) =>
            Object.fromEntries(Object.keys(surfacing).map((name) => [name, row[name] ?? null]))
        )
        expect(read).toEqual([
            {
                surfacing_click_count: 3,
                surfacing_mouse_sum_x_millipx: -(2n ** 53n - 1n),
                surfacing_visited_url_fingerprints: {
                    list: surfacing.surfacing_visited_url_fingerprints.map((element) => ({ element })),
                },
                surfacing_click_target_ids: { list: [{ element: -1n }, { element: 2n ** 53n - 1n }] },
                // parquetjs reads an empty list as a null `list`; Arrow readers see an empty list.
                surfacing_form_field_ids: { list: null },
            },
            {
                surfacing_click_count: null,
                surfacing_mouse_sum_x_millipx: null,
                surfacing_visited_url_fingerprints: null,
                surfacing_click_target_ids: null,
                surfacing_form_field_ids: null,
            },
        ])
    })

    it('reads moments back as a 3-level list of structs and the string lists as lists', async () => {
        const moments = [
            { kind: 'click', window_id: 'w1', ts_ms: 1_000, event_index: 2 ** 31 - 1 },
            { kind: 'full_snapshot_undecoded', window_id: 'w2', ts_ms: 2_000, event_index: 0 },
        ]
        const { rows } = await describeFile(
            await indexRowsToParquet('blocks', [block(moments, ['w1', 'w2']), block([], [])], 1_000)
        )
        const read = rows as Record<string, unknown>[]
        expect(read.map((row) => [row.moments, row.url_fingerprints, row.window_ids])).toEqual([
            [
                { list: moments.map((moment) => ({ element: { ...moment, ts_ms: BigInt(moment.ts_ms) } })) },
                ['w1', 'w2'],
                ['w1', 'w2'],
            ],
            // parquetjs reads an empty repeated field as null and leaves a LIST wrapped; Arrow readers see empty lists.
            [{ list: null }, null, null],
        ])
    })
})
