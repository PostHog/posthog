import { readFileSync, readdirSync, writeFileSync } from 'fs'
import { mkdtempSync } from 'fs'
import { Server, createServer } from 'http'
import { AddressInfo } from 'net'
import os from 'os'
import path from 'path'
import { parse, stringify } from 'yaml'

import { PROFILES_DIR } from '../cards'
import { startAlerts } from './alerts'
import { selectorsOf } from './selectors'

const ENGINE_MS = 120_000
const SCENARIOS_DIR = path.join(__dirname, '..')

type Metrics = { server: Server; url: string }

async function serveMetrics(): Promise<Metrics> {
    const server = createServer((_, response) => {
        response.end('# TYPE synthetic_queue_depth gauge\nsynthetic_queue_depth{queue="q"} 1\n')
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo
    return { server, url: `http://127.0.0.1:${port}/_metrics` }
}

function writeFiles(rules: unknown[]): { rules: string; labels: string } {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'scenario-alerts-test-'))
    const files = { rules: path.join(dir, 'rules.yaml'), labels: path.join(dir, 'labels.yaml') }
    writeFileSync(files.rules, stringify({ groups: [{ name: 'synthetic', interval: '1s', rules }] }))
    writeFileSync(
        files.labels,
        stringify({
            labels: { environment: 'synthetic-env' },
            roles: { 'synthetic-role': { namespace: 'synthetic-ns', pod: 'synthetic-pod-{replica}' } },
        })
    )
    return files
}

describe('alerts on a scenario run', () => {
    let metrics: Metrics
    beforeEach(async () => {
        metrics = await serveMetrics()
    })
    afterEach(async () => {
        await new Promise((resolve) => metrics.server.close(resolve))
    })

    it(
        'names each selector that matched no series as unevaluable, and reports excluded rules',
        async () => {
            const files = writeFiles([
                { alert: 'SyntheticQueueSeen', expr: 'sum(synthetic_queue_depth{queue="q"}) > 100' },
                {
                    alert: 'SyntheticNeedsMissingSeries',
                    expr: 'WITH (lost = sum(synthetic_lost_total{kind="gone"})) sum(synthetic_queue_depth) > 0 and on() lost > 0',
                },
                { alert: 'SyntheticLeftOut', expr: 'sum(synthetic_queue_depth) > 0' },
            ])
            const alerts = await startAlerts({
                alerts: { ...files, exclude: ['SyntheticLeftOut'] },
                targets: [{ role: 'synthetic-role', replica: 0, metricsUrl: metrics.url }],
                scrapeIntervalMs: 1000,
            })
            try {
                const { lines, coverage } = await alerts.finish()

                expect(coverage).toEqual({
                    evaluated: ['SyntheticQueueSeen'],
                    unevaluable: [
                        { rule: 'SyntheticNeedsMissingSeries', selectors: ['synthetic_lost_total{kind="gone"}'] },
                    ],
                    excluded: ['SyntheticLeftOut'],
                })
                expect(lines).toEqual([
                    { type: 'rule', rule: 'SyntheticQueueSeen', state: 'evaluated' },
                    {
                        type: 'rule',
                        rule: 'SyntheticNeedsMissingSeries',
                        state: 'unevaluable',
                        selectors: ['synthetic_lost_total{kind="gone"}'],
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
