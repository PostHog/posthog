import type { LogRecord } from '../log-record-avro'
import { type CompiledMetricRule, type MetricRuleRow, compileMetricRules } from './compile-metric-rules'
import { MetricRulesEmission, buildSizeBoundedPayloads, normalizeMetricRulesWindowMs } from './metric-rules-window'
import { type BatchTallies, createBatchTallies, tallyRecords } from './tally'

const WINDOW_START_MS = 1_700_000_040_000 // a whole minute
const TEAM = 2
const OTHER_TEAM = 3

const record = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: null,
    trace_id: null,
    span_id: null,
    trace_flags: null,
    timestamp: null,
    observed_timestamp: null,
    body: 'hello',
    severity_text: 'ERROR',
    severity_number: 17,
    service_name: 'api',
    resource_attributes: {},
    instrumentation_scope: null,
    event_name: null,
    attributes: { route: '"/a"', duration_ms: '12' },
    ...overrides,
})

const rule = (overrides: Partial<MetricRuleRow> = {}): CompiledMetricRule =>
    compileMetricRules([
        {
            id: 'rule-1',
            metric_name: 'log.requests',
            filter_group: null,
            value_attribute: null,
            group_by: ['attributes.route'],
            version: 1,
            ...overrides,
        },
    ])[0]!

function batch(rules: CompiledMetricRule[], records: LogRecord[], nowMs: number) {
    const tallies: BatchTallies = createBatchTallies()
    tallyRecords(rules, records, tallies, nowMs)
    return { token: 'phc_test', rules, tallies }
}

type SentPayload = { teamId: number; payload: any }

function setup(windowedTeams: number[] = [TEAM]) {
    const sent: SentPayload[] = []
    const emitter = {
        emit: (_token: string, teamId: number, payload: Record<string, unknown>) => {
            sent.push({ teamId, payload })
            return Promise.resolve(true)
        },
    }
    const emission = new MetricRulesEmission(emitter, (teamId) => windowedTeams.includes(teamId), 60_000)
    return { sent, emission }
}

function points(sent: SentPayload[]) {
    return sent.flatMap(({ payload }) =>
        payload.resourceMetrics.flatMap((rm: any) =>
            rm.scopeMetrics.flatMap((sm: any) =>
                sm.metrics.flatMap((m: any) =>
                    (m.sum ?? m.histogram).dataPoints.map((dp: any) => ({
                        name: m.name,
                        route: dp.attributes.find((a: any) => a.key === 'route')?.value.stringValue,
                        timeMs: Number(BigInt(dp.timeUnixNano) / 1_000_000n),
                        dp,
                    }))
                )
            )
        )
    )
}

describe('MetricRulesEmission', () => {
    it('sends one point per series per window with the exact summed count', async () => {
        const { sent, emission } = setup()
        const countRule = rule()
        const batches = [5, 7, 11]
        for (let i = 0; i < batches.length; i++) {
            const records = Array.from({ length: batches[i]! }, () => record())
            await emission.emitBatch(
                new Map([[TEAM, batch([countRule], records, WINDOW_START_MS)]]),
                WINDOW_START_MS + i
            )
        }
        expect(sent).toEqual([])

        await emission.emitBatch(new Map(), WINDOW_START_MS + 60_000)

        const sentPoints = points(sent)
        expect(sentPoints).toHaveLength(1)
        expect(sentPoints[0]).toMatchObject({ name: 'log.requests', route: '/a', timeMs: WINDOW_START_MS })
        expect(sentPoints[0]!.dp.asDouble).toBe(23)
    })

    it('keeps different label sets and teams separate', async () => {
        const { sent, emission } = setup([TEAM, OTHER_TEAM])
        const countRule = rule()
        const records = [
            record(),
            record(),
            record({ attributes: { route: '"/b"' } }),
            record({ attributes: { route: '"/b"' } }),
            record({ attributes: { route: '"/b"' } }),
        ]
        await emission.emitBatch(
            new Map([
                [TEAM, batch([countRule], records, WINDOW_START_MS)],
                [OTHER_TEAM, batch([countRule], [record()], WINDOW_START_MS)],
            ]),
            WINDOW_START_MS
        )
        await emission.emitBatch(
            new Map([[TEAM, batch([countRule], [record()], WINDOW_START_MS)]]),
            WINDOW_START_MS + 1
        )
        await emission.flushAll()

        const byTeam = (teamId: number) =>
            points(sent.filter((s) => s.teamId === teamId)).map((p) => [p.route, p.dp.asDouble])
        expect(byTeam(TEAM)).toEqual([
            ['/a', 3],
            ['/b', 3],
        ])
        expect(byTeam(OTHER_TEAM)).toEqual([['/a', 1]])
    })

    it('adds histogram bucket counts, sums and counts across batches', async () => {
        const { sent, emission } = setup()
        const histogramRule = rule({
            id: 'rule-h',
            metric_name: 'log.duration',
            value_attribute: 'attributes.duration_ms',
        })
        const first = [record({ attributes: { route: '"/a"', duration_ms: '3' } })]
        const second = [
            record({ attributes: { route: '"/a"', duration_ms: '3' } }),
            record({ attributes: { route: '"/a"', duration_ms: '400' } }),
        ]
        await emission.emitBatch(new Map([[TEAM, batch([histogramRule], first, WINDOW_START_MS)]]), WINDOW_START_MS)
        await emission.emitBatch(
            new Map([[TEAM, batch([histogramRule], second, WINDOW_START_MS)]]),
            WINDOW_START_MS + 1
        )
        await emission.flushAll()

        const sentPoints = points(sent)
        expect(sentPoints).toHaveLength(1)
        const dp = sentPoints[0]!.dp
        expect(dp.count).toBe(3)
        expect(dp.sum).toBe(406)
        // Bounds start 0, 5, 10, ..., 250, 500: 3 lands in the second bucket, 400 in the bucket up to 500.
        expect(dp.bucketCounts[1]).toBe(2)
        expect(dp.bucketCounts[8]).toBe(1)
        expect(dp.bucketCounts.reduce((a: number, b: number) => a + b, 0)).toBe(3)
    })

    it('starts a new window for a batch processed after the window ends', async () => {
        const { sent, emission } = setup()
        const countRule = rule()
        await emission.emitBatch(new Map([[TEAM, batch([countRule], [record()], WINDOW_START_MS)]]), WINDOW_START_MS)
        await emission.emitBatch(
            new Map([[TEAM, batch([countRule], [record(), record()], WINDOW_START_MS)]]),
            WINDOW_START_MS + 61_000
        )
        await emission.flushAll()

        expect(points(sent).map((p) => [p.timeMs, p.dp.asDouble])).toEqual([
            [WINDOW_START_MS, 1],
            [WINDOW_START_MS + 60_000, 2],
        ])
    })

    it('keeps a rule edited mid-window from mixing counter and histogram tallies', async () => {
        const { sent, emission } = setup()
        const before = rule()
        const after = rule({ value_attribute: 'attributes.duration_ms' })
        await emission.emitBatch(new Map([[TEAM, batch([before], [record()], WINDOW_START_MS)]]), WINDOW_START_MS)
        await emission.emitBatch(new Map([[TEAM, batch([after], [record()], WINDOW_START_MS)]]), WINDOW_START_MS + 1)
        await emission.flushAll()

        const sentPoints = points(sent)
        expect(sentPoints.map((p) => [p.dp.asDouble ?? null, p.dp.count ?? null])).toEqual([
            [1, null],
            [null, 1],
        ])
    })

    it.each([0, 30_000])(
        'sends an expired window when no further batch arrives, after %d ms of other exports',
        async (exportMs) => {
            jest.useFakeTimers()
            try {
                jest.setSystemTime(WINDOW_START_MS)
                const sent: SentPayload[] = []
                const slowEmitter = {
                    emit: (_token: string, teamId: number, payload: Record<string, unknown>) => {
                        jest.setSystemTime(Date.now() + exportMs)
                        sent.push({ teamId, payload })
                        return Promise.resolve(true)
                    },
                }
                const mixed = new MetricRulesEmission(slowEmitter, (teamId) => teamId === TEAM, 60_000)
                await mixed.emitBatch(
                    new Map([
                        [TEAM, batch([rule()], [record(), record()], WINDOW_START_MS)],
                        [OTHER_TEAM, batch([rule()], [record()], WINDOW_START_MS)],
                    ])
                )
                sent.length = 0
                await jest.advanceTimersByTimeAsync(59_999 - exportMs)
                expect(sent).toEqual([])

                await jest.advanceTimersByTimeAsync(1)
                expect(points(sent).map((p) => [p.timeMs, p.dp.asDouble])).toEqual([[WINDOW_START_MS, 2]])
            } finally {
                jest.useRealTimers()
            }
        }
    )

    it('sends the open window on a revoke flush and keeps the idle timer for later windows', async () => {
        jest.useFakeTimers()
        try {
            jest.setSystemTime(WINDOW_START_MS)
            const { sent, emission } = setup()
            await emission.emitBatch(new Map([[TEAM, batch([rule()], [record()], WINDOW_START_MS)]]))
            await emission.flushOpen()
            expect(points(sent).map((p) => [p.timeMs, p.dp.asDouble])).toEqual([[WINDOW_START_MS, 1]])

            sent.length = 0
            await emission.emitBatch(new Map([[TEAM, batch([rule()], [record(), record()], WINDOW_START_MS)]]))
            await jest.advanceTimersByTimeAsync(60_000)
            expect(points(sent).map((p) => [p.timeMs, p.dp.asDouble])).toEqual([[WINDOW_START_MS, 2]])
        } finally {
            jest.useRealTimers()
        }
    })

    it('waits for an idle flush still sending when shutdown starts', async () => {
        jest.useFakeTimers()
        try {
            jest.setSystemTime(WINDOW_START_MS)
            let release!: () => void
            const gate = new Promise<void>((resolve) => (release = resolve))
            const sentTeams: number[] = []
            const emitter = {
                emit: async (_token: string, teamId: number) => {
                    await gate
                    sentTeams.push(teamId)
                    return true
                },
            }
            const emission = new MetricRulesEmission(emitter, () => true, 60_000)
            await emission.emitBatch(
                new Map([
                    [TEAM, batch([rule()], [record()], WINDOW_START_MS)],
                    [OTHER_TEAM, batch([rule()], [record()], WINDOW_START_MS)],
                ])
            )
            await jest.advanceTimersByTimeAsync(60_000)

            let stopped = false
            const stopping = emission.flushAll().then(() => (stopped = true))
            await Promise.resolve()
            expect(stopped).toBe(false)

            release()
            await stopping
            expect(sentTeams).toEqual([TEAM, OTHER_TEAM])
        } finally {
            jest.useRealTimers()
        }
    })

    it('runs one idle flush at a time when the endpoint is slower than the window', async () => {
        jest.useFakeTimers()
        try {
            jest.setSystemTime(WINDOW_START_MS)
            let release!: () => void
            const gate = new Promise<void>((resolve) => (release = resolve))
            let inFlight = 0
            let maxInFlight = 0
            const sentTimes: number[] = []
            const emitter = {
                emit: async (_token: string, _teamId: number, payload: any) => {
                    inFlight++
                    maxInFlight = Math.max(maxInFlight, inFlight)
                    await gate
                    inFlight--
                    sentTimes.push(...points([{ teamId: TEAM, payload }]).map((p) => p.timeMs))
                    return true
                },
            }
            const emission = new MetricRulesEmission(emitter, () => true, 60_000)
            await emission.emitBatch(new Map([[TEAM, batch([rule()], [record()], WINDOW_START_MS)]]))
            await jest.advanceTimersByTimeAsync(60_000)
            await emission.emitBatch(new Map([[TEAM, batch([rule()], [record()], WINDOW_START_MS)]]))
            await jest.advanceTimersByTimeAsync(60_000)
            expect(maxInFlight).toBe(1)

            release()
            await jest.advanceTimersByTimeAsync(0)
            expect(sentTimes).toEqual([WINDOW_START_MS, WINDOW_START_MS + 60_000])
            expect(maxInFlight).toBe(1)
        } finally {
            jest.useRealTimers()
        }
    })

    it('splits a window too large for one request and sends every label set once', () => {
        const routes = Array.from({ length: 40 }, (_, i) => `/route-${i}`)
        const records = routes.map((route) => record({ attributes: { route: JSON.stringify(route) } }))
        const { rules, tallies } = batch([rule()], records, WINDOW_START_MS)
        const maxBytes = 2_000

        const payloads = buildSizeBoundedPayloads(rules, tallies, WINDOW_START_MS, maxBytes)

        expect(payloads.length).toBeGreaterThan(1)
        for (const payload of payloads) {
            expect(Buffer.byteLength(JSON.stringify(payload))).toBeLessThanOrEqual(maxBytes)
        }
        const sentRoutes = points(payloads.map((payload) => ({ teamId: TEAM, payload }))).map((p) => p.route)
        expect(sentRoutes.sort()).toEqual([...routes].sort())
    })

    it('sends teams outside the allowlist once per batch, as before', async () => {
        const { sent, emission } = setup([])
        const countRule = rule()
        await emission.emitBatch(new Map([[TEAM, batch([countRule], [record()], WINDOW_START_MS)]]), WINDOW_START_MS)
        await emission.emitBatch(
            new Map([[TEAM, batch([countRule], [record()], WINDOW_START_MS)]]),
            WINDOW_START_MS + 1
        )
        expect(points(sent).map((p) => p.dp.asDouble)).toEqual([1, 1])
    })

    it.each([
        [60_000, 60_000],
        [15_000, 20_000],
        [1, 10_000],
        [0, 60_000],
        [Number.NaN, 60_000],
    ])('normalizes a %d ms window to %d ms', (input, expected) => {
        expect(normalizeMetricRulesWindowMs(input)).toBe(expected)
    })
})
