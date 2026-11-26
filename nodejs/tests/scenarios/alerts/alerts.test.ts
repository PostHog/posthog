import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'fs'
import { Server, createServer } from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'
import { parse, stringify } from 'yaml'

import { PROFILES_DIR } from '../cards'
import { AlertLine, AlertTransition, startAlerts } from './alerts'
import { selectorsOf } from './selectors'

const ENGINE_MS = 120_000
const TRANSITION_MS = 60_000
const GROUP_INTERVAL_MS = 1000
const DAY_S = 24 * 60 * 60
const SCENARIOS_DIR = path.join(__dirname, '..')

type Metrics = { server: Server; url: string; set(value: number): void }

async function serveMetrics(initial: number): Promise<Metrics> {
    let depth = initial
    const server = createServer((_, response) => {
        response.end(`# TYPE synthetic_queue_depth gauge\nsynthetic_queue_depth{queue="q"} ${depth}\n`)
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
                            expr: 'max by (pod, environment) (synthetic_queue_depth{namespace="synthetic-ns"}) > 10',
                            for: '2s',
                            labels: { severity: 'warning' },
                            annotations: { runbook_url: 'https://example.com/runbook' },
                        },
                    ],
                },
            ])
            const transitions = transitionsSeen()
            const alerts = await startAlerts({
                alerts: { ...files, exclude: [] },
                targets: [{ role: 'synthetic-role', replica: 0, metricsUrl: metrics.url }],
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
                const { lines, coverage } = await alerts.finish({ startedAt: driveStartedAt }, [
                    { valve: 'role.freeze', target: 'synthetic-role', requestedAt: appliedAt, appliedAt },
                ])

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
                })
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
                        { alert: 'SyntheticLeftOut', expr: 'sum(synthetic_queue_depth) > 0' },
                        { record: 'synthetic:queue_depth:sum', expr: 'sum(synthetic_queue_depth)' },
                    ],
                },
                {
                    name: 'synthetic-daily',
                    interval: '24h',
                    eval_offset: `${(Math.floor(Date.now() / 1000) + DAY_S / 2) % DAY_S}s`,
                    rules: [{ alert: 'SyntheticNeverEvaluated', expr: 'sum(synthetic_queue_depth) > 100' }],
                },
            ])
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
                const { lines, coverage } = await alerts.finish({ startedAt: Date.now() }, [])

                const neverEvaluated = 'vmalert did not evaluate it during the run'
                expect(coverage).toEqual({
                    evaluated: ['SyntheticQueueSeen'],
                    fired: [],
                    unevaluable: [
                        { rule: 'SyntheticNeedsMissingSeries', selectors: ['synthetic_lost_total{kind="gone"}'] },
                        { rule: 'SyntheticNeverEvaluated', selectors: [], error: neverEvaluated },
                    ],
                    excluded: ['SyntheticLeftOut'],
                })
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
    ])('%s', (_, expr, selectors) => {
        expect(selectorsOf(expr)).toEqual(selectors)
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
