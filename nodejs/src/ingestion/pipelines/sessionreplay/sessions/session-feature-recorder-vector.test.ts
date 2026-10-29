import { readFileSync, writeFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'
import { getValidEvents } from '~/ingestion/pipelines/sessionreplay/parse-message-step'

import { SessionFeatureRecorder } from './session-feature-recorder'

/**
 * The v4 recorder in `rust/ai-research/replay-core-v4` computes these values for each block it stores, and its tests
 * read this vector. To change what the recorder computes, change it here, then run this test with
 * WRITE_FEATURE_VECTOR=1 to write the vector again, and make the Rust tests pass against it.
 */
const VECTOR_PATH = path.join(__dirname, 'session-feature-recorder-vector.json')

type Event = Record<string, unknown>

interface VectorMessage {
    window_id: string
    events: Event[]
}

interface VectorBlock {
    messages: VectorMessage[]
    expected: Record<string, unknown>
}

interface VectorCase {
    name: string
    blocks: VectorBlock[]
}

// Ingestion keeps any positive event time, so the vector keeps them short.
const T = 1_000_000

const incremental = (ms: number, data: Record<string, unknown>): Event => ({
    type: 3,
    timestamp: T + ms,
    data,
})
const mouseMove = (ms: number, positions: unknown[]): Event => incremental(ms, { source: 1, positions })
const interaction = (ms: number, type: unknown, fields: Record<string, unknown> = {}): Event =>
    incremental(ms, { source: 2, type, ...fields })
const click = (ms: number, x: number, y: number, id: number): Event => interaction(ms, 2, { x, y, id })
const scroll = (ms: number, fields: Record<string, unknown>): Event => incremental(ms, { source: 3, ...fields })
const input = (ms: number, fields: Record<string, unknown>): Event => incremental(ms, { source: 5, ...fields })
const selection = (ms: number): Event => incremental(ms, { source: 14, ranges: [] })
const meta = (ms: number, href: unknown, fields: Record<string, unknown> = {}): Event => ({
    type: 4,
    timestamp: T + ms,
    data: { href, width: 1280, height: 720, ...fields },
})
const custom = (ms: number, tag: string, payload: unknown): Event => ({
    type: 5,
    timestamp: T + ms,
    data: { tag, payload },
})
const plugin = (ms: number, name: string, payload?: unknown): Event => ({
    type: 6,
    timestamp: T + ms,
    data: payload === undefined ? { plugin: name } : { plugin: name, payload },
})
const consoleLog = (ms: number, level?: string): Event =>
    plugin(ms, 'rrweb/console@1', level === undefined ? { trace: [] } : { level, trace: [], payload: ['"x"'] })

const message = (events: Event[], window_id = 'w1'): VectorMessage => ({ window_id, events })

/** One block per list of messages. */
const blocks = (...messages: VectorMessage[][]): VectorMessage[][] => messages

const CASES: Array<{ name: string; blocks: VectorMessage[][] }> = [
    {
        name: 'mouse positions: sums, distance, direction changes and velocity',
        blocks: blocks([
            message([
                mouseMove(1_000, [
                    { x: 10, y: 20, id: 1, timeOffset: -30 },
                    { x: 13, y: 24, id: 1, timeOffset: -20 },
                    // No time passes, so no velocity, and no movement turns the direction.
                    { x: 13, y: 24, id: 1, timeOffset: -20 },
                    { x: 5.5, y: 10.25, id: 1, timeOffset: -5 },
                    { x: 40, y: 50, id: 1 },
                    // A falsy item is skipped.
                    null,
                    0,
                ]),
                mouseMove(1_100, [
                    { x: 20, y: 30, id: 1, timeOffset: 0 },
                    { x: 60, y: 30, id: 1, timeOffset: 10 },
                    { x: 20, y: 30, id: 1, timeOffset: 20 },
                ]),
                incremental(1_200, { source: 1 }),
            ]),
            // Another window's positions continue the same path, earlier in time, so they add no velocity.
            message([mouseMove(1_050, [{ x: 1000.75, y: 800.5, id: 2, timeOffset: 0 }])], 'w2'),
        ]),
    },
    {
        name: 'scrolls: magnitude, reversals, scroll to top and the scroll target',
        blocks: blocks([
            message([
                scroll(1_000, { id: 1, x: 0, y: 0 }),
                scroll(1_100, { id: 1, x: 0, y: 300 }),
                scroll(1_200, { id: 1, x: 0, y: 500.5 }),
                // Up within 500 ms of the last scroll: a rapid reversal.
                scroll(1_400, { id: 1, x: 0, y: 200 }),
                scroll(2_400, { id: 1, x: 0, y: 900 }),
                scroll(2_500, { id: 1, x: 0, y: 900 }),
                scroll(2_600, { id: 1, x: 0, y: 0 }),
                // A new target starts again.
                scroll(2_700, { id: 2, x: 0, y: 50 }),
                scroll(2_800, { id: 2, x: 0, y: 20 }),
                scroll(2_850, { id: 2, x: 0 }),
                // A scroll without a target starts again every time.
                scroll(2_900, { x: 0, y: 100 }),
                scroll(3_000, { x: 0, y: 400 }),
                // A null target continues after one without a target.
                scroll(3_100, { id: null, x: 0, y: 100 }),
                scroll(3_200, { id: null, x: 0, y: 700 }),
                scroll(3_300, { id: 3, x: 0, y: -50 }),
                scroll(3_400, { id: 3, x: 0, y: 12000.25 }),
            ]),
        ]),
    },
    {
        name: 'clicks: rage and dead clicks, click kinds, targets and touches',
        blocks: blocks([
            message([
                click(1_000, 100, 100, 5),
                click(1_200, 110, 105, 5),
                click(1_400, 112, 100, 6),
                interaction(1_500, 4, { x: 112, y: 101, id: 6 }),
                click(4_000, 500, 500, 7),
                // The lone click at 4000 did nothing before this one: it was dead.
                interaction(7_000, 3, { x: 900, y: 900, id: 8 }),
                meta(7_500, 'https://shop.example.com/after'),
                // A navigation came after the lone click at 7000, so it was not dead.
                interaction(10_000, 9, { x: 100, y: 100, id: 9 }),
                interaction(13_000, 2, { id: 10 }),
                click(13_100, 100, 100, 5),
                click(13_500, 100.4, 100.6, -1),
                interaction(13_600, 0, { x: 100, y: 100, id: 5 }),
                interaction(13_700, 1, { x: 100, y: 100, id: 5 }),
                interaction(13_800, '2', { x: 100, y: 100, id: 11 }),
                interaction(13_900, 5, { id: 12 }),
                interaction(14_000, 6, { id: 12 }),
                interaction(14_100, 7, { x: 300, y: 300, id: 13 }),
                incremental(14_200, { source: 6, positions: [{ x: 1, y: 1, id: 13, timeOffset: 0 }] }),
            ]),
        ]),
    },
    {
        name: 'typing: form fields, backspaces in UTF-16 units and copies after a selection',
        blocks: blocks([
            message([
                input(1_000, { id: 20, text: 'hello', isChecked: false }),
                input(1_100, { id: 20, text: 'hel', isChecked: false }),
                input(1_200, { id: 20, text: 'help me', isChecked: false }),
                input(1_300, { id: 21, text: '😀ab', isChecked: false }),
                input(1_400, { id: 21, text: 'a', isChecked: false }),
                input(1_500, { id: 22, text: 'on', isChecked: true }),
                input(1_600, { text: 'no target', isChecked: false }),
                input(1_700, { id: 23, text: 42 }),
                input(1_800, { id: 24, text: 'line\n"quoted" \u0001 é 日本 😀' }),
                input(1_900, { id: 24, text: 'line' }),
                selection(2_000),
                input(3_500, { id: 20, text: 'help', isChecked: false }),
                input(3_600, { id: 20, text: 'hel', isChecked: false }),
                selection(5_000),
                input(7_001, { id: 20, text: 'he', isChecked: false }),
                selection(8_000),
                click(8_100, 10, 10, 30),
            ]),
        ]),
    },
    {
        name: 'gaps between actions, and console errors after them',
        blocks: blocks([
            message([
                consoleLog(500, 'error'),
                click(1_000, 10, 10, 1),
                click(1_000, 10, 10, 1),
                input(41_000, { id: 2, text: 'a' }),
                click(41_100, 500, 500, 1),
                // Out of order: a negative gap does not count, but the next gap starts from it.
                input(2_000, { id: 2, text: 'ab' }),
                click(2_500, 10, 10, 1),
                consoleLog(7_499, 'error'),
                consoleLog(7_500, 'error'),
                consoleLog(2_400, 'error'),
                consoleLog(7_600, 'warn'),
                consoleLog(7_700, 'info'),
                consoleLog(7_800),
            ]),
        ]),
    },
    {
        name: 'navigations: page URLs, quick backs and path tokens',
        blocks: blocks([
            message([
                meta(1_000, 'https://shop.example.com/Account/Settings?tab=billing#checkout'),
                custom(1_500, '$url_changed', { href: 'https://shop.example.com/cart' }),
                meta(1_800, 'https://shop.example.com/cart'),
                custom(1_900, '$json_ld', { href: 'https://shop.example.com/login' }),
                meta(2_000, 'https://shop.example.com/admin', { tag: '$json_ld' }),
                meta(5_000, '   '),
                meta(5_100, '', { payload: { href: ' https://shop.example.com/login/login/LOGIN ' } }),
                meta(9_000, '﻿https://shop.example.com/admin '),
                meta(12_000, '/settings/404?next=/login#checkout'),
                meta(15_000, 'dashboard'),
                meta(18_000, 'https://shop.example.com/error%2Flogin'),
                meta(21_000, 'https://shop.example.com/onboarding/../refund'),
                meta(24_000, 'HTTPS://SHOP.EXAMPLE.COM/CANCEL/'),
                meta(27_000, '/checKout'),
                meta(30_000, 7),
                custom(33_000, '$url_changed', { href: 'https://shop.example.com/signup' }),
                custom(33_100, '$url_changed', { href: 'https://shop.example.com/checkout/billing' }),
                custom(33_200, '$url_changed', { href: 'https://shop.example.com/dashboard/error' }),
            ]),
            message(
                [
                    // `hrefFrom` reads any event: a click that names a page navigates after the click is counted.
                    interaction(40_000, 2, { x: 1, y: 1, id: 1, href: 'https://shop.example.com/login' }),
                    plugin(40_500, 'rrweb/console@1', { level: 'log', href: 'https://shop.example.com/account' }),
                    {
                        type: 2,
                        timestamp: T + 41_000,
                        data: {
                            node: { type: 0, childNodes: [], id: 1 },
                            initialOffset: { left: 0, top: 0 },
                            href: 'https://shop.example.com/settings',
                        },
                    },
                    incremental(41_500, {
                        source: 0,
                        adds: [],
                        removes: [],
                        texts: [],
                        attributes: [],
                        payload: { href: 'https://shop.example.com/refund' },
                    }),
                ],
                'w2'
            ),
        ]),
    },
    {
        name: 'network requests from both network plugins',
        blocks: blocks([
            message([
                plugin(1_000, 'rrweb/network@1', {
                    requests: [
                        { status: 200, duration: 12.5 },
                        { status: 404, duration: 0 },
                        { status: 503, duration: -1 },
                        { status: null, responseStatus: 418, duration: 30.25 },
                        { responseStatus: 502, duration: 0.1 },
                        { status: 600 },
                        { status: 302, duration: 1000 },
                        { status: '500', duration: 7.000000000000001 },
                        7,
                    ],
                }),
                plugin(1_100, 'rrweb/network@1', { requests: { status: 500 } }),
                plugin(1_200, 'posthog/network@1', { '21': 500, '39': 120.5, '0': 'https://api.example.com' }),
                plugin(1_300, 'posthog/network@1', { '21': 404 }),
                plugin(1_400, 'posthog/network@1', {}),
                plugin(1_500, 'posthog/network@1', ''),
                plugin(1_600, 'posthog/network@1', 0),
                plugin(1_700, 'posthog/network@1', 'x'),
                plugin(1_800, 'posthog/network@1', null),
                plugin(1_900, 'posthog/network@1'),
                plugin(2_000, 'posthog/network@1', [1, 2]),
                plugin(2_100, 'other/plugin@1', { requests: [{ status: 500 }] }),
            ]),
        ]),
    },
    {
        name: 'mutations, resizes, touches and events with nothing to record',
        blocks: blocks([
            message([
                { type: 0, timestamp: T + 1_000, data: {} },
                { type: 1, timestamp: T + 1_001, data: {} },
                meta(1_002, 'https://shop.example.com/'),
                {
                    type: 2,
                    timestamp: T + 1_003,
                    data: { node: { type: 0, childNodes: [], id: 1 }, initialOffset: { left: 0, top: 0 } },
                },
                { type: 2, timestamp: T + 1_004, data: '\u001f\u008bnot gzip', cv: '2024-10' },
                incremental(1_005, { source: 0, adds: [], removes: [], texts: [], attributes: [] }),
                { ...incremental(1_006, { source: 0, adds: '\u001f\u008b', removes: [] }), cv: '2024-10' },
                incremental(1_007, { source: 4, width: 390, height: 844 }),
                incremental(1_008, { source: 6, positions: [] }),
                incremental(1_009, { source: 7, type: 0, id: 3 }),
                incremental(1_010, { source: 8, id: 4, adds: [] }),
                selection(1_011),
                custom(1_012, '$pageview', {}),
                { type: 3, timestamp: T + 1_013 },
                { type: 99, timestamp: T + 1_014, data: { source: 2, type: 2 } },
            ]),
        ]),
    },
    {
        name: 'events that ingestion drops before its recorder',
        blocks: blocks(
            [
                message([
                    { type: 3, data: { source: 2, type: 2, x: 1, y: 1, id: 1 } },
                    { type: 3, timestamp: 0, data: { source: 2, type: 2, x: 1, y: 1, id: 2 } },
                    { type: 3, timestamp: -5, data: { source: 2, type: 2, x: 1, y: 1, id: 3 } },
                    { type: 3, timestamp: String(T), data: { source: 2, type: 2, x: 1, y: 1, id: 4 } },
                    { type: 3, timestamp: 9e15, data: { source: 2, type: 2, x: 1, y: 1, id: 5 } },
                ]),
                message([click(1_000, 1, 1, 6), { type: 3, timestamp: null, data: { source: 5, id: 7 } }]),
            ],
            [message([{ type: 4, timestamp: 0, data: { href: 'https://shop.example.com/' } }])]
        ),
    },
    {
        name: 'the recorder starts again at each block',
        blocks: blocks(
            [
                message([
                    mouseMove(1_000, [{ x: 10, y: 10, id: 1, timeOffset: 0 }]),
                    scroll(1_000, { id: 1, x: 0, y: 100 }),
                    meta(1_000, 'https://shop.example.com/a'),
                    input(1_100, { id: 1, text: 'abc' }),
                    selection(1_200),
                    click(1_300, 10, 10, 1),
                    click(1_400, 10, 10, 1),
                ]),
            ],
            [
                message([
                    click(1_500, 10, 10, 1),
                    mouseMove(1_600, [{ x: 50, y: 50, id: 1, timeOffset: 0 }]),
                    scroll(1_600, { id: 1, x: 0, y: 0 }),
                    meta(1_700, 'https://shop.example.com/b'),
                    input(1_800, { id: 1, text: 'a' }),
                    consoleLog(1_900, 'error'),
                ]),
            ],
            [message([consoleLog(2_000, 'warn')])]
        ),
    },
    {
        name: 'each set keeps the first thousand values, and so does the backspace memory',
        blocks: blocks([
            message([
                // Each click also names a page, so that it fills both sets.
                ...Array.from({ length: 1_001 }, (_, i) =>
                    interaction(1_000 + i, 2, { id: i + 1, href: `https://a.example/${i + 1}` })
                ),
                ...Array.from({ length: 1_001 }, (_, i) => input(3_000 + i, { id: i + 1, text: 'ab' })),
                input(7_000, { id: 1_001, text: 'a' }),
                input(7_001, { id: 1, text: 'a' }),
            ]),
        ]),
    },
]

/** What ingestion's recorder emits for one batch of these messages, after its parse step drops invalid events. */
function recordBatch(messages: VectorMessage[]): Record<string, unknown> {
    const recorder = new SessionFeatureRecorder('session', 1, 'batch', 100)
    for (const { window_id, events } of messages) {
        const valid = getValidEvents(events, 0)
        if (!valid) {
            continue
        }
        recorder.recordMessage({
            distinct_id: 'd',
            session_id: 'session',
            token: null,
            eventsByWindowId: { [window_id]: valid.validEvents },
            eventsRange: { start: valid.startDateTime, end: valid.endDateTime },
            snapshot_source: 'web',
            snapshot_library: 'web',
            metadata: { partition: 0, topic: 'test', offset: 0, timestamp: 0, rawSize: 0 },
        })
    }
    const { startDateTime: _start, endDateTime: _end, ...values } = recorder.end()!
    return {
        ...values,
        visitedUrls: [...values.visitedUrls].sort(),
        clickTargetIds: [...values.clickTargetIds].sort((a, b) => a - b),
        formFieldIds: [...values.formFieldIds].sort((a, b) => a - b),
    }
}

function buildVector(): { cases: VectorCase[] } {
    return {
        cases: CASES.map(({ name, blocks }) => ({
            name,
            blocks: blocks.map((messages) => {
                // As capture's JSON delivers them, so that both recorders read the same values.
                const delivered: VectorMessage[] = parseJSON(JSON.stringify(messages))
                return { messages: delivered, expected: recordBatch(parseJSON(JSON.stringify(delivered))) }
            }),
        })),
    }
}

describe('session feature recorder test vector', () => {
    it('is what the recorder computes for each block of each case', () => {
        const vector = buildVector()
        if (process.env.WRITE_FEATURE_VECTOR) {
            writeFileSync(VECTOR_PATH, JSON.stringify(vector) + '\n')
        }
        expect(vector).toEqual(parseJSON(readFileSync(VECTOR_PATH, 'utf8')))
    })
})
