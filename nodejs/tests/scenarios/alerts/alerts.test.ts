import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import { Server, createServer } from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'
import { parse, stringify } from 'yaml'

import { PROFILES_DIR } from '../cards'
import { AlertCoverage, AlertGap, AlertLine, AlertTransition, recordAlerts, startAlerts } from './alerts'
import { Engine } from './engine'
import { readsOf, selectorsOf } from './selectors'

const ENGINE_MS = 120_000
const TRANSITION_MS = 60_000
const GROUP_INTERVAL_MS = 1000
const DAY_S = 24 * 60 * 60
const SCENARIOS_DIR = path.join(__dirname, '..')

type Metrics = { server: Server; url: string; set(value: number): void }

async function serveMetrics(initial: number): Promise<Metrics> {
    let depth = initial
    const server = createServer((request, response) => {
        const shard = new URL(request.url ?? '/', 'http://localhost').searchParams.get('shard') ?? ''
        response.end(`# TYPE synthetic_queue_depth gauge\nsynthetic_queue_depth{queue="q",shard="${shard}"} ${depth}\n`)
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    return { server, url: `http://127.0.0.1:${port}/_metrics`, set: (value) => (depth = value) }
}

const fixtureDirs: string[] = []

function writeFiles(groups: { name: string; interval: string; eval_offset?: string; rules: unknown[] }[]): {
    rules: string
    labels: string
} {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-alerts-test-'))
    fixtureDirs.push(dir)
    const files = { rules: path.join(dir, 'rules.yaml'), labels: path.join(dir, 'labels.yaml') }
    writeFileSync(files.rules, stringify({ groups }))
    writeFileSync(
        files.labels,
        stringify({
            labels: { environment: 'synthetic-env' },
            roles: { 'synthetic-role': { namespace: 'synthetic-ns', pod: 'synthetic-pod-{replica}' } },
        })
    )
    return files
}

async function closedPortUrl(): Promise<string> {
    const server = createServer()
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    await new Promise((resolve) => server.close(resolve))
    return `http://127.0.0.1:${port}/_metrics`
}

function transitionsSeen(): {
    seen: AlertTransition[]
    reach(state: string): Promise<void>
    record(t: AlertTransition): void
} {
    const seen: AlertTransition[] = []
    const waiting: { state: string; resolve(): void }[] = []
    return {
        seen,
        record(transition) {
            seen.push(transition)
            waiting.filter(({ state }) => state === transition.state).forEach(({ resolve }) => resolve())
        },
        reach: (state) =>
            seen.some((transition) => transition.state === state)
                ? Promise.resolve()
                : new Promise((resolve, reject) => {
                      waiting.push({ state, resolve })
                      setTimeout(() => reject(new Error(`no ${state} transition`)), TRANSITION_MS).unref()
                  }),
    }
}

// A real engine on a busy host can miss an evaluation, but never before the run began.
const gapsBefore = (coverage: AlertCoverage, at: number): AlertGap[] =>
    ('gaps' in coverage ? coverage.gaps : []).filter(({ from }) => from < at)

describe('alerts on a scenario run', () => {
    let metrics: Metrics
    beforeEach(async () => {
        metrics = await serveMetrics(0)
    })
    afterEach(async () => {
        await new Promise((resolve) => metrics.server.close(resolve))
        fixtureDirs.splice(0).forEach((dir) => rmSync(dir, { recursive: true, force: true }))
    })

    it(
        'records pending, firing and resolved with the value, the threshold and the times since the drive and the valve',
        async () => {
            const files = writeFiles([
                {
                    name: 'synthetic',
                    interval: `${GROUP_INTERVAL_MS}ms`,
                    rules: [
                        {
                            alert: 'SyntheticQueueDeepWarning',
                            expr: 'max by (pod, environment) (synthetic_queue_depth{namespace="synthetic-ns", shard="a", queue!="a>1"}) > 10',
                            for: '2s',
                            labels: { severity: 'warning' },
                            annotations: { runbook_url: 'https://example.com/runbook' },
                        },
                    ],
                },
            ])
            const transitions = transitionsSeen()
            const engineAskedAt = Date.now()
            const alerts = await startAlerts({
                alerts: { ...files, exclude: [] },
                targets: [{ role: 'synthetic-role', replica: 0, metricsUrl: `${metrics.url}?shard=a` }],
                onTransition: transitions.record,
                scrapeIntervalMs: 1000,
                pollMs: 500,
            })
            try {
                const driveStartedAt = Date.now()
                metrics.set(50)
                await transitions.reach('firing')
                const appliedAt = new Date().toISOString()
                metrics.set(0)
                await transitions.reach('resolved')
                const { lines, coverage } = await alerts.finish(
                    { startedAt: driveStartedAt },
                    [{ valve: 'role.freeze', target: 'synthetic-role', requestedAt: appliedAt, appliedAt }],
                    Date.now()
                )

                const recorded = lines.filter((line) => line.type === 'transition')
                expect(recorded.map(({ state }) => state)).toEqual(['pending', 'firing', 'resolved'])
                expect(recorded[1]).toMatchObject({
                    rule: 'SyntheticQueueDeepWarning',
                    instance: recorded[0].instance,
                    tier: 'warning',
                    labels: { pod: 'synthetic-pod-0', environment: 'synthetic-env' },
                    value: 50,
                    threshold: { op: '>', value: 10 },
                    for: 2,
                    runbook: 'https://example.com/runbook',
                })
                expect(recorded[2]).toMatchObject({ instance: recorded[0].instance, value: null })
                expect(recorded[1].sinceDriveMs).toBeGreaterThan(0)
                expect(recorded[2].sinceValves).toEqual([
                    { valve: 'role.freeze', target: 'synthetic-role', sinceMs: expect.any(Number) },
                ])
                expect(recorded[2].sinceValves[0].sinceMs).toBeGreaterThan(0)
                expect(coverage).toEqual({
                    evaluated: ['SyntheticQueueDeepWarning'],
                    fired: ['SyntheticQueueDeepWarning'],
                    unevaluable: [],
                    excluded: [],
                    gaps: expect.any(Array),
                })
                expect(gapsBefore(coverage, engineAskedAt)).toEqual([])
                expect(transitions.seen.map(({ state }) => state)).toEqual(['pending', 'firing', 'resolved'])
            } finally {
                await alerts.close()
            }
        },
        ENGINE_MS
    )

    it(
        'names each selector that matched no series and each rule never evaluated as unevaluable, and reports excluded rules',
        async () => {
            metrics.set(1)
            const files = writeFiles([
                {
                    name: 'synthetic',
                    interval: `${GROUP_INTERVAL_MS}ms`,
                    rules: [
                        { alert: 'SyntheticQueueSeen', expr: 'sum(synthetic_queue_depth{queue="q"}) > 100' },
                        {
                            alert: 'SyntheticNeedsMissingSeries',
                            expr: 'WITH (lost = sum(synthetic_lost_total{kind="gone"})) sum(synthetic_queue_depth) > 0 and on() lost > 0',
                        },
                        { alert: 'SyntheticOffsetBeforeRun', expr: 'sum(synthetic_queue_depth offset 1h) > 100' },
                        { alert: 'SyntheticLeftOut', expr: 'sum(synthetic_queue_depth) > 0' },
                        { record: 'synthetic:queue_depth:sum', expr: 'sum(synthetic_queue_depth)' },
                        { record: 'up', expr: 'vector(1)' },
                    ],
                },
                {
                    name: 'synthetic-daily',
                    interval: '24h',
                    eval_offset: `${(Math.floor(Date.now() / 1000) + DAY_S / 2) % DAY_S}s`,
                    rules: [{ alert: 'SyntheticNeverEvaluated', expr: 'sum(synthetic_queue_depth) > 100' }],
                },
            ])
            const engineAskedAt = Date.now()
            const alerts = await startAlerts({
                alerts: { ...files, exclude: ['SyntheticLeftOut'] },
                targets: [
                    { role: 'synthetic-role', replica: 0, metricsUrl: metrics.url },
                    { role: 'synthetic-role', replica: 1, metricsUrl: await closedPortUrl() },
                ],
                onTransition: () => undefined,
                scrapeIntervalMs: 1000,
                pollMs: 500,
            })
            try {
                await sleep(2 * GROUP_INTERVAL_MS)
                const { lines, coverage } = await alerts.finish({ startedAt: Date.now() }, [], Date.now())

                const neverEvaluated = 'vmalert did not evaluate it during the run'
                expect(coverage).toEqual({
                    evaluated: ['SyntheticQueueSeen'],
                    fired: [],
                    unevaluable: [
                        { rule: 'SyntheticNeedsMissingSeries', selectors: ['synthetic_lost_total{kind="gone"}'] },
                        { rule: 'SyntheticOffsetBeforeRun', selectors: ['synthetic_queue_depth offset 3600s'] },
                        { rule: 'SyntheticNeverEvaluated', selectors: [], error: neverEvaluated },
                    ],
                    excluded: ['SyntheticLeftOut'],
                    gaps: expect.any(Array),
                })
                expect(gapsBefore(coverage, engineAskedAt)).toEqual([])
                expect(
                    lines.filter((line): line is Extract<AlertLine, { type: 'rule' }> => line.type === 'rule')
                ).toEqual([
                    { type: 'rule', rule: 'SyntheticQueueSeen', state: 'evaluated' },
                    {
                        type: 'rule',
                        rule: 'SyntheticNeedsMissingSeries',
                        state: 'unevaluable',
                        selectors: ['synthetic_lost_total{kind="gone"}'],
                    },
                    {
                        type: 'rule',
                        rule: 'SyntheticOffsetBeforeRun',
                        state: 'unevaluable',
                        selectors: ['synthetic_queue_depth offset 3600s'],
                    },
                    {
                        type: 'rule',
                        rule: 'SyntheticNeverEvaluated',
                        state: 'unevaluable',
                        selectors: [],
                        error: neverEvaluated,
                    },
                    { type: 'rule', rule: 'SyntheticLeftOut', state: 'excluded' },
                ])
            } finally {
                await alerts.close()
            }
        },
        ENGINE_MS
    )

    type Seen = { state: 'pending' | 'firing' | 'resolved'; evaluatedAfterMs: number; value: string }
    const snapshotOf = (activeAt: number, interval: number, duration: number, seen: Seen): unknown => ({
        data: {
            groups: [
                {
                    interval,
                    rules: [
                        {
                            id: '1',
                            name: 'SyntheticQueueDeep',
                            query: 'synthetic_queue_depth > 10',
                            duration,
                            lastError: '',
                            lastEvaluation: new Date(activeAt + seen.evaluatedAfterMs).toISOString(),
                            alerts:
                                seen.state === 'resolved'
                                    ? []
                                    : [
                                          {
                                              id: '2',
                                              state: seen.state,
                                              activeAt: new Date(activeAt).toISOString(),
                                              value: seen.value,
                                              labels: {},
                                          },
                                      ],
                        },
                    ],
                },
            ],
        },
    })
    const engineAnswering = (answers: unknown[], thenFail: boolean): Engine => {
        let reads = 0
        return {
            alerting: () =>
                reads < answers.length
                    ? Promise.resolve(answers[reads++]).then((answer) =>
                          answer instanceof Error ? Promise.reject(answer) : answer
                      )
                    : thenFail
                      ? Promise.reject(new Error('vmalert went away'))
                      : Promise.resolve(answers.at(-1)),
            metrics: (endpoint, { query }) =>
                Promise.resolve(endpoint === '/expand-with-exprs' ? { expr: query } : { data: [{}] }),
            stop: () => Promise.resolve(),
        }
    }
    const recordedFrom = (
        engine: Engine
    ): { alerts: ReturnType<typeof recordAlerts>; firing: Promise<void>; reach(state: string): Promise<void> } => {
        const transitions = transitionsSeen()
        const alerts = recordAlerts(engine, Math.floor(Date.now() / 1000), [], {
            alerts: { rules: 'rules.yaml', labels: 'labels.yaml', exclude: [] },
            targets: [],
            onTransition: transitions.record,
            pollMs: 10,
        })
        return { alerts, firing: transitions.reach('firing'), reach: transitions.reach }
    }
    const firstSeenFiring: Seen = { state: 'firing', evaluatedAfterMs: 3000, value: '50' }

    it.each<
        [string, number, number, Seen[], number, { pendingValue: number | null; firedAfterMs: number; fired: string[] }]
    >([
        [
            'a firing first seen two evaluations late',
            1,
            2,
            [firstSeenFiring],
            5000,
            { pendingValue: null, firedAfterMs: 2000, fired: ['SyntheticQueueDeep'] },
        ],
        [
            'an evaluation that stayed pending past the grid',
            1,
            2,
            [{ state: 'pending', evaluatedAfterMs: 2700, value: '12' }, firstSeenFiring],
            5000,
            { pendingValue: 12, firedAfterMs: 3000, fired: ['SyntheticQueueDeep'] },
        ],
        [
            'a pending evaluation on the grid point',
            1,
            2,
            [{ state: 'pending', evaluatedAfterMs: 2000, value: '12' }, firstSeenFiring],
            5000,
            { pendingValue: 12, firedAfterMs: 3000, fired: ['SyntheticQueueDeep'] },
        ],
        [
            'a pending evaluation that started late',
            1,
            2,
            [{ state: 'pending', evaluatedAfterMs: 350, value: '12' }, firstSeenFiring],
            5000,
            { pendingValue: 12, firedAfterMs: 2000, fired: ['SyntheticQueueDeep'] },
        ],
        [
            'an interval that does not divide in floating point',
            0.3,
            2.1,
            [firstSeenFiring],
            5000,
            { pendingValue: null, firedAfterMs: 2100, fired: ['SyntheticQueueDeep'] },
        ],
        [
            'a firing seen only after missed evaluations, which may have fired after the judge started',
            1,
            2,
            [
                { state: 'pending', evaluatedAfterMs: 1000, value: '12' },
                { state: 'firing', evaluatedAfterMs: 4000, value: '50' },
            ],
            3500,
            { pendingValue: 12, firedAfterMs: 2000, fired: [] },
        ],
        [
            'a firing after the judge started',
            1,
            2,
            [firstSeenFiring],
            1000,
            { pendingValue: null, firedAfterMs: 2000, fired: [] },
        ],
    ])('dates %s by the evaluation it fired at', async (_, interval, duration, seen, judgedAfterMs, expected) => {
        const activeAt = Date.now() - 5000
        const { alerts, firing } = recordedFrom(
            engineAnswering(
                seen.map((answer) => snapshotOf(activeAt, interval, duration, answer)),
                false
            )
        )
        await firing

        const { lines, coverage } = await alerts.finish({ startedAt: activeAt }, [], activeAt + judgedAfterMs)

        expect(lines.filter((line) => line.type === 'transition')).toEqual([
            expect.objectContaining({ state: 'pending', at: activeAt, value: expected.pendingValue }),
            expect.objectContaining({ state: 'firing', at: activeAt + expected.firedAfterMs, value: 50 }),
        ])
        expect(coverage).toMatchObject({ fired: expected.fired })
    })

    it('bounds a resolution between the evaluation after the last one that showed the alert and the one that missed it', async () => {
        const activeAt = Date.now() - 6000
        const { alerts, reach } = recordedFrom(
            engineAnswering(
                [
                    snapshotOf(activeAt, 1, 0, { state: 'firing', evaluatedAfterMs: 2350, value: '50' }),
                    snapshotOf(activeAt, 1, 0, { state: 'resolved', evaluatedAfterMs: 5350, value: '' }),
                ],
                false
            )
        )
        await reach('resolved')

        const { lines, coverage } = await alerts.finish({ startedAt: activeAt }, [], Date.now())

        expect(lines.filter((line) => line.type === 'transition')).toEqual([
            expect.objectContaining({ state: 'firing', at: activeAt }),
            expect.objectContaining({ state: 'resolved', at: activeAt + 3000, latest: activeAt + 5350 }),
        ])
        expect(coverage).toMatchObject({
            gaps: [
                {
                    from: activeAt + 2350,
                    to: activeAt + 5350,
                    reason: 'missed evaluations',
                    rules: ['SyntheticQueueDeep'],
                },
            ],
        })
    })

    it('closes the old cycle when the same alert comes back with a new activeAt', async () => {
        const activeAt = Date.now() - 6000
        const { alerts, reach } = recordedFrom(
            engineAnswering(
                [
                    snapshotOf(activeAt, 1, 0, { state: 'firing', evaluatedAfterMs: 1000, value: '50' }),
                    snapshotOf(activeAt + 3000, 1, 0, { state: 'firing', evaluatedAfterMs: 0, value: '60' }),
                ],
                false
            )
        )
        await reach('resolved')

        const { lines } = await alerts.finish({ startedAt: activeAt }, [], Date.now())

        expect(lines.filter((line) => line.type === 'transition')).toEqual([
            expect.objectContaining({ state: 'firing', at: activeAt, value: 50 }),
            expect.objectContaining({ state: 'resolved', at: activeAt + 2000, latest: activeAt + 3000 }),
            expect.objectContaining({ state: 'firing', at: activeAt + 3000, value: 60 }),
        ])
    })

    it('reports the window a failed read left without evidence', async () => {
        const activeAt = Date.now() - 6000
        const { alerts, reach } = recordedFrom(
            engineAnswering(
                [
                    snapshotOf(activeAt, 1, 0, { state: 'firing', evaluatedAfterMs: 1000, value: '50' }),
                    new Error('vmalert restarted'),
                    snapshotOf(activeAt, 1, 0, { state: 'resolved', evaluatedAfterMs: 3000, value: '' }),
                ],
                false
            )
        )
        await reach('resolved')

        const { lines, coverage } = await alerts.finish({ startedAt: activeAt }, [], Date.now())

        const gap = { from: expect.any(Number), to: expect.any(Number), reason: 'vmalert restarted' }
        expect(coverage).toMatchObject({ gaps: [gap] })
        expect(lines).toContainEqual({ type: 'gap', ...gap })
    })

    it('keeps the transitions it recorded when the final read fails', async () => {
        const activeAt = Date.now() - 5000
        const { alerts, firing } = recordedFrom(engineAnswering([snapshotOf(activeAt, 1, 0, firstSeenFiring)], true))
        await firing

        const { lines, coverage } = await alerts.finish({ startedAt: activeAt }, [], Date.now())

        expect(lines).toEqual([expect.objectContaining({ type: 'transition', state: 'firing', at: activeAt })])
        expect(coverage).toEqual({ unread: 'the alert read failed: vmalert went away' })
    })

    it('refuses a rules file that names an alert twice before any container starts', async () => {
        const files = writeFiles([
            { name: 'first', interval: '1s', rules: [{ alert: 'SyntheticTwice', expr: 'synthetic_queue_depth > 1' }] },
            { name: 'second', interval: '1s', rules: [{ alert: 'SyntheticTwice', expr: 'synthetic_queue_depth > 2' }] },
        ])
        const alerts = await startAlerts({
            alerts: { ...files, exclude: [] },
            targets: [],
            onTransition: () => undefined,
        })

        await expect(alerts.finish({ startedAt: Date.now() }, [], Date.now())).resolves.toEqual({
            lines: [],
            coverage: {
                unread: 'the alert engine did not start: the rules file names the alert SyntheticTwice more than once',
            },
        })
    })
})

describe('selectorsOf', () => {
    it.each([
        ['a selector with matchers', 'sum(rate(x_total{a="b"}[5m])) > 1', ['x_total{a="b"}']],
        ['grouping labels are no selectors', 'sum by (namespace, pod) (x) / sum(y) by (pod)', ['x', 'y']],
        ['braces and words inside strings', 'label_replace(x{a="}"}, "dst", "$1", "src", "(sum) {b}")', ['x{a="}"}']],
        ['offsets, subqueries and numbers', 'min_over_time(x[6h:5m] offset 2m) > 1e3 unless on() vector(0)', ['x']],
        ['a bare matcher', '{__name__=~"a|b"} == 1', ['{__name__=~"a|b"}']],
        [
            'the MetricsQL default and atan2 operators',
            '(sum(rate(x[5m])) default 0) > 1 or (y atan2 z)',
            ['x', 'y', 'z'],
        ],
        ['a limit and a join prefix', 'sum(x) by (q) limit 3 * on (q) group_left (p) prefix "rhs_" y', ['x', 'y']],
        ['metrics named like the limit keyword', 'sum(limit) > 0 or limit{a="b"} > 1', ['limit', 'limit{a="b"}']],
        ['a group modifier without labels', 'x + on(q) group_left y', ['x', 'y']],
        [
            'metrics named like keywords and modifiers',
            'sum(group_left) > 0 or sum(default{queue="q"}) > 0 or sum(by, on) > 0',
            ['group_left', 'default{queue="q"}', 'by', 'on'],
        ],
        ['infinity and NaN as operands', 'clamp_max(x, inf) > 0 or y != nan', ['x', 'y']],
    ])('%s', (_, expr, selectors) => {
        expect(selectorsOf(expr)).toEqual(selectors)
    })
})

describe('readsOf', () => {
    it.each([
        [
            'an offset after a range and after a bare selector',
            'rate(x{a="b"}[1h] offset 15m) + y offset 1h30m',
            [
                { selector: 'x{a="b"}', offsetSeconds: 900 },
                { selector: 'y', offsetSeconds: 5400 },
            ],
        ],
        [
            'a subquery offset reaches every selector inside it',
            'max_over_time((sum(rate(z[5m])) + v offset 1m)[10m:1m] offset 30m) + w',
            [
                { selector: 'z', offsetSeconds: 1800 },
                { selector: 'v', offsetSeconds: 1860 },
                { selector: 'w', offsetSeconds: 0 },
            ],
        ],
        ['a negative offset', 'q offset -5m', [{ selector: 'q', offsetSeconds: -300 }]],
        [
            'one selector read with two offsets',
            'x - x offset 1d',
            [
                { selector: 'x', offsetSeconds: 0 },
                { selector: 'x', offsetSeconds: 86400 },
            ],
        ],
    ])('%s', (_, expr, reads) => {
        expect(readsOf(expr)).toEqual(reads)
    })
})

describe('the public tree', () => {
    const yamlFiles = (dir: string): string[] =>
        readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
            entry.isDirectory()
                ? yamlFiles(path.join(dir, entry.name))
                : /\.ya?ml$/.test(entry.name)
                  ? [path.join(dir, entry.name)]
                  : []
        )

    it('carries no alert rules and no profile that names them', () => {
        const withRules = yamlFiles(SCENARIOS_DIR).filter((file) => {
            const value = parse(readFileSync(file, 'utf8')) as { groups?: { rules?: unknown }[] } | null
            return Array.isArray(value?.groups) && value.groups.some((group) => group?.rules !== undefined)
        })
        const profilesWithAlerts = yamlFiles(PROFILES_DIR).filter(
            (file) => (parse(readFileSync(file, 'utf8')) as { alerts?: unknown }).alerts !== undefined
        )
        expect({ withRules, profilesWithAlerts }).toEqual({ withRules: [], profilesWithAlerts: [] })
    })
})
