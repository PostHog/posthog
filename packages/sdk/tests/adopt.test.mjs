import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { createApiToolLibrary } from '@posthog/mcp/dist/cli-library.mjs'
import { foldDrift, generateDefinitions, loadStack, typeCheckStack } from '@posthog/sdk/stack'

const sdk = fileURLToPath(new URL('..', import.meta.url))
const validator = createApiToolLibrary()
const folders = []

after(() => {
    for (const folder of folders) {
        rmSync(folder, { recursive: true, force: true })
    }
})

// A repository with this SDK and its TypeScript installed, and a stack folder holding `files`.
function repository(files) {
    const base = mkdtempSync(join(tmpdir(), 'stack-adopt-'))
    folders.push(base)
    mkdirSync(join(base, '.git'))
    mkdirSync(join(base, 'node_modules', '@posthog'), { recursive: true })
    symlinkSync(sdk, join(base, 'node_modules', '@posthog', 'sdk'))
    symlinkSync(
        dirname(createRequire(import.meta.url).resolve('typescript/package.json')),
        join(base, 'node_modules', 'typescript')
    )
    writeFileSync(join(base, 'package.json'), JSON.stringify({ type: 'module' }))
    writeFileSync(
        join(base, 'tsconfig.json'),
        JSON.stringify({
            compilerOptions: {
                strict: true,
                module: 'ESNext',
                moduleResolution: 'bundler',
                skipLibCheck: true,
                noEmit: true,
            },
        })
    )
    const folder = join(base, 'stack')
    for (const file of files) {
        mkdirSync(dirname(join(folder, file.path)), { recursive: true })
        writeFileSync(join(folder, file.path), file.contents)
    }
    return folder
}

const resources = JSON.parse(
    readFileSync(new URL('fixtures/stack-all-kinds/description.json', import.meta.url), 'utf8')
).resources
const bodies = (list) =>
    list.map(({ kind, key, body, depends_on }) => ({ kind, key, body, ...(depends_on ? { depends_on } : {}) }))

test('generated definitions evaluate back to the resources they came from, and type-check', async () => {
    const files = generateDefinitions(resources)
    assert.deepEqual(generateDefinitions([...resources].reverse()), files)
    const folder = repository(files)
    const loaded = await loadStack(folder, { validator })
    assert.deepEqual(loaded.problems, [])
    assert.deepEqual(bodies(loaded.description.resources), bodies(resources))
    const types = await typeCheckStack(folder)
    assert.deepEqual([types.status, types.problems], ['passed', []])
})

// Entities as the engine reads them from PostHog: the API's own shapes, nulls and defaults included.
const fromPostHog = [
    {
        kind: 'insight',
        key: 'pageviews',
        body: {
            name: null,
            derived_name: 'Pageview count',
            description: '',
            tags: [],
            deleted: false,
            dashboards: [5],
            query: {
                kind: 'InsightVizNode',
                full: true,
                source: {
                    kind: 'TrendsQuery',
                    series: [{ kind: 'EventsNode', event: '$pageview', name: '$pageview', math: 'total' }],
                    interval: 'day',
                    dateRange: { date_from: '-7d', explicitDate: false },
                    trendsFilter: { display: 'ActionsLineGraph' },
                    filterTestAccounts: false,
                    properties: [],
                    breakdownFilter: { breakdown_type: 'event' },
                    version: 2,
                },
            },
        },
    },
    {
        kind: 'insight',
        key: 'grouped',
        body: {
            name: 'Grouped',
            query: {
                kind: 'InsightVizNode',
                source: {
                    kind: 'TrendsQuery',
                    series: [{ kind: 'EventsNode', event: '$pageview' }],
                    breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                    properties: {
                        type: 'AND',
                        values: [
                            {
                                type: 'AND',
                                values: [{ key: 'email', type: 'person', value: 'x', operator: 'icontains' }],
                            },
                        ],
                    },
                },
            },
        },
    },
    {
        kind: 'flag',
        key: 'beta',
        body: {
            key: 'beta',
            name: 'Beta',
            active: true,
            ensure_experience_continuity: false,
            tags: [],
            filters: {
                groups: [{ variant: null, properties: [], rollout_percentage: 100 }],
                payloads: {},
                multivariate: null,
            },
        },
    },
    {
        kind: 'flag',
        key: 'split',
        body: {
            key: 'split',
            name: '',
            active: false,
            ensure_experience_continuity: false,
            tags: ['checkout'],
            filters: {
                aggregation_group_type_index: null,
                groups: [
                    {
                        variant: null,
                        properties: [{ key: 'email', type: 'person', operator: 'is_set', value: 'is_set' }],
                        rollout_percentage: 50,
                    },
                ],
                multivariate: {
                    variants: [
                        { key: 'control', name: '', rollout_percentage: 50 },
                        { key: 'test', name: 'Test', rollout_percentage: 50 },
                    ],
                },
                payloads: { control: '{"a":1}' },
            },
        },
    },
]

test('an entity PostHog returned generates a definition that passes check and type-checks', async () => {
    const folder = repository(generateDefinitions(fromPostHog))
    const loaded = await loadStack(folder, { validator })
    assert.deepEqual(
        loaded.problems.filter((problem) => problem.severity === 'error'),
        []
    )
    assert.deepEqual(
        bodies(loaded.description.resources),
        bodies([...fromPostHog].sort((a, b) => (a.kind + a.key < b.kind + b.key ? -1 : 1)))
    )
    const types = await typeCheckStack(folder)
    assert.deepEqual([types.status, types.problems], ['passed', []])
})

test('generation prefers the builders and keeps Markdown as files', () => {
    const byPath = new Map(generateDefinitions(resources).map((file) => [file.path, file.contents]))
    assert.ok(byPath.get('events.ts').includes("plan: prop.enum(['free', 'team', 'scale']),"))
    assert.ok(byPath.get('flags.ts').includes('variants: { control: 50, test: 50 },'))
    assert.ok(byPath.get('views.ts').includes("insight('revenue-mrr_sum_of_mrr_usd_by_month', hogql({"))
    assert.equal(
        byPath.get('context/projects/2/plans.md'),
        readFileSync(new URL('fixtures/stack-all-kinds/context/plans.md', import.meta.url), 'utf8')
    )
})

test('a definition the folder already has is referred to, not written again', () => {
    const files = generateDefinitions(resources, { existingKeys: ['model:mrr'] })
    const models = files.find((file) => file.path === 'models.ts').contents
    assert.ok(!models.includes("model('mrr'"))
    assert.ok(files.find((file) => file.path === 'metrics.ts').contents.includes("ref('model', 'mrr')"))
})

test('drift in a literal is folded into the file, and computed values are left to the caller', async () => {
    const folder = repository([
        { path: 'index.ts', contents: "export * from './views'\n" },
        {
            path: 'views.ts',
            contents: `import { hogql, insight } from '@posthog/sdk/define'

const suffix = 'weekly'

export const signups = insight('signups', hogql({ name: 'Signups', description: \`Signups \${suffix}\`, query: 'select 1', display: 'ActionsTable' }))
`,
        },
    ])
    const result = await foldDrift(folder, [
        {
            kind: 'insight',
            key: 'signups',
            fields: [
                { path: 'name', pushed: 'Signups', found: "Sign-ups (renamed in PostHog's UI)" },
                { path: 'description', pushed: 'Signups weekly', found: 'Signups by week' },
                { path: 'query.source.query', pushed: 'select 1', found: 'select 2' },
                { path: 'query.display', pushed: 'ActionsBar', found: 'ActionsLineGraph' },
            ],
        },
    ])
    const file = 'stack/views.ts'
    assert.deepEqual(result, {
        applied: [
            {
                kind: 'insight',
                key: 'signups',
                file,
                path: 'name',
                before: 'Signups',
                after: "Sign-ups (renamed in PostHog's UI)",
            },
            {
                kind: 'insight',
                key: 'signups',
                file,
                path: 'query.source.query',
                before: 'select 1',
                after: 'select 2',
            },
        ],
        manual: [
            {
                kind: 'insight',
                key: 'signups',
                file,
                path: 'description',
                pushed: 'Signups weekly',
                found: 'Signups by week',
                reason: 'the value is computed in code, not written as a literal',
            },
            {
                kind: 'insight',
                key: 'signups',
                file,
                path: 'query.display',
                pushed: 'ActionsBar',
                found: 'ActionsLineGraph',
                reason: 'the file no longer holds the pushed value, so it changed since the push',
            },
        ],
    })
    assert.ok(
        readFileSync(join(folder, 'views.ts'), 'utf8').includes(
            "hogql({ name: 'Sign-ups (renamed in PostHog\\'s UI)', description: `Signups ${suffix}`, query: 'select 2', display: 'ActionsTable' })"
        )
    )
})
