import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { after, test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { createApiToolLibrary } from '@posthog/mcp/dist/cli-library.mjs'
import {
    alert,
    check as qualityCheck,
    contextPage,
    dashboard,
    destination,
    endpoint,
    event,
    experiment,
    flag,
    hogql,
    insight,
    metric,
    model,
    prop,
    ref,
    secret,
    source,
    sql,
    survey,
    text,
    tile,
    trend,
} from '@posthog/sdk/define'
import {
    evaluateExports,
    formatDescription,
    loadStack,
    typeCheckStack,
    validateDescription,
    validateStructure,
} from '@posthog/sdk/stack'

const root = fileURLToPath(new URL('..', import.meta.url))
const here = 'tests/stack.test.mjs'
const validator = createApiToolLibrary()
const fixture = (name) => fileURLToPath(new URL(`fixtures/${name}`, import.meta.url))
const temporary = []

after(() => {
    for (const folder of temporary) {
        rmSync(folder, { recursive: true, force: true })
    }
})

function check(exports) {
    const evaluation = evaluateExports(exports, { root })
    const problems = [
        ...evaluation.problems,
        ...validateDescription(evaluation.description, { validator, origins: evaluation.origins }),
    ]
    return { description: evaluation.description, problems }
}

// The whole diagnostic, so a wrong kind, key, path or file fails the test, not just a wrong code.
const tuples = (problems) =>
    problems.map(({ code, severity, kind, key, path, file }) => [code, severity, kind, key, path, file])

const sqlInsight = (name) => hogql({ name, query: 'select 1' })
const target = insight('target', sqlInsight('Target'))
const bound = { configuration: { type: 'absolute', bounds: { upper: 1 } } }
const alertOn = (insightRef, extra = {}) =>
    alert('watch', { insight: insightRef, subscribed_users: [1], threshold: bound, ...extra })

test('the description does not depend on export order or field order', () => {
    const build = (reversed) => {
        const a = insight(
            'a',
            reversed ? { query: sqlInsight('A').query, name: 'A' } : { name: 'A', query: sqlInsight('A').query }
        )
        const b = insight('b', { name: 'B', query: sqlInsight('B').query })
        const board = dashboard('board', { name: 'Board', tiles: [tile(a), tile(b)] })
        return reversed ? { board, b, a } : { a, b, board }
    }
    const first = formatDescription(check(build(false)).description)
    const second = formatDescription(check(build(true)).description)
    assert.equal(first, second)
    assert.deepEqual(
        JSON.parse(first).resources.map(({ kind, key }) => `${kind}:${key}`),
        ['dashboard:board', 'insight:a', 'insight:b']
    )
})

test('a reordered dashboard keeps the keys and bodies of the insights its tiles make', () => {
    const tiles = [
        trend({ name: 'Weekly signups', series: [{ event: 'signed_up' }] }),
        tile(sqlInsight('Revenue'), { key: 'revenue' }),
        text('## Notes'),
    ]
    const insights = (order) => {
        const { description } = check({ board: dashboard('board', { name: 'Board', tiles: order }) })
        return description.resources.filter((resource) => resource.kind === 'insight')
    }
    const forward = insights(tiles)
    assert.deepEqual(
        forward.map((resource) => resource.key),
        ['board-revenue', 'board-weekly_signups']
    )
    assert.deepEqual(insights([...tiles].reverse()), forward)
})

test('a dashboard lists itself on the insights its tiles show, and defaults their layouts', () => {
    const shown = insight('shown', sqlInsight('Shown'))
    const { description, problems } = check({
        board: dashboard('board', { name: 'Board', tiles: [shown, text('Hi')] }),
    })
    assert.deepEqual(problems, [])
    const [board, insightResource] = description.resources
    assert.deepEqual(insightResource.body.dashboards, [{ $ref: { kind: 'dashboard', key: 'board' } }])
    assert.deepEqual(
        board.body.tiles.map((entry) => entry.layouts.sm),
        [
            { x: 0, y: 0, w: 6, h: 5 },
            { x: 0, y: 5, w: 12, h: 2 },
        ]
    )
})

const loop = { note: 'x' }
loop.self = loop
const inner = destination('hook', { name: 'Inner' })
const listed = insight('listed', { ...sqlInsight('Listed'), dashboards: 'invalid' })
const checkout = event('checkout', { properties: { total: prop.number().required() } })
const revenue = model('revenue', {
    columns: { total: 'number', day: 'date' },
    query: sql`select ${checkout.props.nope} from events where event = ${checkout}`,
})

const cases = [
    [
        'a key outside the key rule',
        { bad: insight('Bad Key', sqlInsight('Bad')) },
        [['key_invalid', 'error', 'insight', 'Bad Key', undefined, here]],
    ],
    [
        'two definitions with one key and equal bodies',
        { one: insight('same', sqlInsight('Same')), two: insight('same', sqlInsight('Same')) },
        [['key_duplicate', 'error', 'insight', 'same', undefined, here]],
    ],
    [
        'a definition nested in another with the same identity',
        { outer: destination('hook', { name: 'Outer', filters: { properties: [{ value: ref(inner) }] } }) },
        [
            ['key_duplicate', 'error', 'destination', 'hook', undefined, here],
            ['reference_cycle', 'error', 'destination', 'hook', undefined, here],
        ],
    ],
    [
        'two tiles whose names give one key',
        { board: dashboard('board', { tiles: [sqlInsight('Same'), sqlInsight('Same!')] }) },
        [['key_duplicate', 'error', 'insight', 'board-same', undefined, here]],
    ],
    [
        'a ref to nothing',
        { watch: alertOn(ref('insight', 'nowhere')) },
        [['reference_missing', 'error', 'alert', 'watch', 'insight', here]],
    ],
    [
        'a ref of the wrong kind',
        { target, watch: alertOn(dashboard('board', { tiles: [target] })) },
        [['reference_kind', 'error', 'alert', 'watch', 'insight', here]],
    ],
    [
        'an id where a definition belongs',
        { watch: alertOn(42) },
        [['reference_required', 'error', 'alert', 'watch', 'insight', here]],
    ],
    [
        'a tile ref that reads the name instead of the id',
        { target, board: dashboard('board', { tiles: [tile(ref(target, 'name'))] }) },
        [['reference_attr', 'error', 'dashboard', 'board', 'tiles[0].insight', here]],
    ],
    [
        'refs and values in tile fields that take neither',
        {
            target,
            board: dashboard('board', {
                tiles: [
                    { insight: target, color: ref(target, 'name') },
                    { insight: null },
                    { insight: target, show_description: 'sometimes' },
                ],
            }),
        },
        [
            ['reference_position', 'error', 'dashboard', 'board', 'tiles[0].color', here],
            ['reference_required', 'error', 'dashboard', 'board', 'tiles[1].insight', here],
            ['tile_invalid', 'error', 'dashboard', 'board', 'tiles[2].show_description', here],
        ],
    ],
    [
        'an insight ref among the users an alert notifies',
        { target, watch: alertOn(target, { subscribed_users: [target] }) },
        [['reference_position', 'error', 'alert', 'watch', 'subscribed_users[0]', here]],
    ],
    [
        'two destinations that refer to each other by key',
        {
            x: destination('x', { name: 'X', filters: { properties: [{ value: ref('destination', 'y') }] } }),
            y: destination('y', { name: 'Y', filters: { properties: [{ value: ref('destination', 'x') }] } }),
        },
        [['reference_cycle', 'error', 'destination', 'x', undefined, here]],
    ],
    [
        'a body that contains itself',
        { looped: insight('looped', { ...sqlInsight('Looped'), description: loop }) },
        [
            ['value_invalid', 'error', 'insight', 'looped', 'description.self', here],
            ['schema_invalid', 'error', 'insight', 'looped', 'description', here],
        ],
    ],
    [
        'a misspelled bound, which the schema would drop',
        {
            target,
            watch: alertOn(target, { threshold: { configuration: { type: 'absolute', bounds: { uppper: 1 } } } }),
        },
        [
            ['threshold_bounds_missing', 'error', 'alert', 'watch', 'threshold.configuration.bounds', here],
            ['unknown_field', 'error', 'alert', 'watch', 'threshold.configuration.bounds.uppper', here],
        ],
    ],
    [
        'a value outside the schema',
        { target, watch: alertOn(target, { calculation_interval: 'fortnightly' }) },
        [['schema_invalid', 'error', 'alert', 'watch', 'calculation_interval', here]],
    ],
    [
        'a trend whose query is not one',
        {
            odd: insight(
                'odd',
                trend({ kind: 'UnexpectedKind', interval: 'fortnightly', series: [{ kind: 'MadeUp', event: 42 }] })
            ),
        },
        [
            ['schema_invalid', 'error', 'insight', 'odd', 'query.source.interval', here],
            ['schema_invalid', 'error', 'insight', 'odd', 'query.source.series[0]', here],
        ],
    ],
    [
        'a create step the type leaves out',
        { copy: dashboard('copy', { name: 'Copy', use_dashboard: 12345 }) },
        [['field_not_allowed', 'error', 'dashboard', 'copy', 'use_dashboard', here]],
    ],
    [
        'an invalid dashboards list on an insight a tile shows',
        { listed, board: dashboard('board', { tiles: [listed] }) },
        [['schema_invalid', 'error', 'insight', 'listed', 'dashboards', here]],
    ],
    [
        'a text tile with no text',
        { board: dashboard('board', { tiles: [text('')] }) },
        [['schema_invalid', 'error', 'dashboard', 'board', 'tiles[0].text.body', here]],
    ],
    [
        'a function in a body',
        { target: insight('target', { ...sqlInsight('Target'), description: () => 'x' }) },
        [['value_invalid', 'error', 'insight', 'target', 'description', here]],
    ],
    [
        'a property and columns the definitions do not declare',
        {
            revenue,
            total: metric('total', { description: 'Total', from: revenue, column: 'nope', dimensions: ['plan'] }),
            filled: qualityCheck('filled', { subject: revenue, column_name: 'missing', check_type: 'not_null' }),
        },
        [
            ['column_undeclared', 'error', 'check', 'filled', 'column_name', here],
            ['property_undeclared', 'error', 'model', 'revenue', 'query.query', here],
            ['column_undeclared', 'error', 'metric', 'total', 'definition', here],
            ['column_undeclared', 'error', 'metric', 'total', 'dimensions', here],
        ],
    ],
    [
        'an event whose enforcement and property types are outside the generated schemas, with enum values they lack',
        {
            signup: event('signup', {
                enforcement: 'strict',
                properties: {
                    plan: prop.enum(['free', 'paid']),
                    seats: { ...prop.number(), property_type: 'Integer' },
                },
            }),
        },
        [
            ['schema_invalid', 'error', 'event', 'signup', 'enforcement_mode', here],
            ['schema_invalid', 'error', 'property_group', 'signup', 'properties[1].property_type', here],
        ],
    ],
    [
        'a credential in plain text and a check subject that is neither a model nor an id',
        {
            warehouse: source('warehouse', {
                source_type: 'Postgres',
                payload: { password: 'hunter2', token: secret('TOKEN') },
            }),
            orphan: qualityCheck('orphan', {
                subject_type: 'view',
                subject_uuid: 'not-a-uuid',
                check_type: 'not_null',
            }),
        },
        [
            ['subject_invalid', 'error', 'check', 'orphan', 'subject_uuid', here],
            ['secret_inline', 'error', 'source', 'warehouse', 'payload.password', here],
        ],
    ],
    [
        'a flag key outside the flag key rule',
        { odd: flag('Bad Key!') },
        [['key_invalid', 'error', 'flag', 'Bad Key!', undefined, here]],
    ],
    [
        'wiki pages the wiki would refuse: no frontmatter, a bad status, and a title another page has',
        {
            bare: contextPage('areas/bare.md', { content: '# Bare\n' }),
            first: contextPage('areas/first.md', {
                content: '---\nsummary: One.\nstatus: active\n---\n# Same title\n',
            }),
            second: contextPage('areas/second.md', {
                content: '---\nsummary: Two.\nstatus: draft\n---\n# Same  Title!\n',
            }),
        },
        [
            ['context_page_refused', 'error', 'context_page', 'areas/bare.md', 'content', here],
            ['context_page_refused', 'error', 'context_page', 'areas/bare.md', 'content', here],
            ['context_page_refused', 'error', 'context_page', 'areas/second.md', 'content', here],
            ['context_page_refused', 'error', 'context_page', 'areas/second.md', 'content', here],
        ],
    ],
    [
        'an endpoint placeholder that names no declared variable, and a variable keyed by something other than an id',
        {
            byAccount: endpoint('by-account', {
                query: {
                    kind: 'HogQLQuery',
                    query: 'select 1 where account = {variables.account_id} and plan = {variables.plan}',
                    variables: { plan: { code_name: 'plan', variableId: 'plan' } },
                },
            }),
        },
        [
            ['variable_undeclared', 'warning', 'endpoint', 'by-account', 'query.query', here],
            ['variable_invalid', 'error', 'endpoint', 'by-account', 'query.variables.plan', here],
        ],
    ],
    [
        'a layout field PostHog does not keep, and a tile wider than the grid',
        {
            board: dashboard('board', {
                tiles: [text('Hi', { layouts: { sm: { x: 8, y: 0, w: 6, h: 2, minW: 3, i: '0' } } })],
            }),
        },
        [
            ['tile_invalid', 'error', 'dashboard', 'board', 'tiles[0].layouts.sm', here],
            ['layout_field_dropped', 'warning', 'dashboard', 'board', 'tiles[0].layouts.sm', here],
        ],
    ],
    [
        'variants set through filters, which typed().variant() would not know',
        { split: flag('split', { filters: { multivariate: { variants: [{ key: 'a', rollout_percentage: 100 }] } } }) },
        [['flag_field_moved', 'error', 'flag', 'split', 'filters.multivariate', here]],
    ],
    [
        'an insight query key check does not know, which PostHog saves as written',
        {
            odd: insight('odd', {
                query: {
                    kind: 'InsightVizNode',
                    full: true,
                    source: { kind: 'TrendsQuery', series: [], intreval: 'day' },
                },
            }),
        },
        [['unknown_field', 'warning', 'insight', 'odd', 'query.source.intreval', here]],
    ],
]

for (const [name, exports, expected] of cases) {
    test(`reports ${name}`, () => {
        assert.deepEqual(tuples(check(exports).problems), expected)
    })
}

test('depends_on lists what a body reads by name, and leaves out refs, events and itself', () => {
    const purchase = event('purchase', { properties: { total: prop.number() } })
    const orders = model('orders', {
        columns: { total: 'number', day: 'date' },
        query: sql`select ${purchase.props.total} as total, toDate(timestamp) as day from events where event = ${purchase}`,
    })
    const daily = model('daily', {
        columns: { total: 'number', day: 'date' },
        query: sql`select day, sum(total) as total from ${orders} group by day`,
    })
    const rollout = flag('rollout', { variants: ['control', 'test'] })
    const { description, problems } = check({
        daily,
        total: metric('total', { description: 'Total', from: daily, column: 'total' }),
        filled: qualityCheck('filled', { subject: daily, column_name: 'day', check_type: 'not_null' }),
        api: endpoint('daily-api', { query: sql`select * from ${daily} join ${orders} on true` }),
        chart: insight('chart', hogql({ name: 'Chart', query: sql`select * from ${daily}` })),
        board: dashboard('board', { tiles: [trend(daily, { sum: 'total' })] }),
        test: experiment('rollout_test', { name: 'Rollout', feature_flag_key: rollout }),
        ask: survey('ask', { name: 'Ask', type: 'popover', linked_flag_id: rollout, questions: [] }),
    })
    assert.deepEqual(tuples(problems.filter((problem) => problem.severity === 'error')), [])
    const dependsOn = Object.fromEntries(
        description.resources.map((resource) => [`${resource.kind}:${resource.key}`, resource.depends_on])
    )
    assert.deepEqual(dependsOn, {
        'dashboard:board': undefined,
        'endpoint:daily-api': [
            { kind: 'model', key: 'daily' },
            { kind: 'model', key: 'orders' },
        ],
        'experiment:rollout_test': [{ kind: 'flag', key: 'rollout' }],
        'flag:rollout': undefined,
        'insight:board-daily_sum_of_total_by_day': [{ kind: 'model', key: 'daily' }],
        'insight:chart': [{ kind: 'model', key: 'daily' }],
        'metric:total': [{ kind: 'model', key: 'daily' }],
        'model:daily': [{ kind: 'model', key: 'orders' }],
        'model:orders': undefined,
        'check:filled': undefined,
        'survey:ask': undefined,
    })
    assert.match(
        description.resources.find((resource) => resource.key === 'orders').body.query.query,
        /toFloat\(properties\.total\)/
    )
})

test('check reports a dependency the stack lacks, and dependencies in a loop', () => {
    const model = (key, dependsOn) => ({
        kind: 'model',
        key,
        body: { name: key, query: { kind: 'HogQLQuery', query: 'select 1' }, columns: {} },
        depends_on: dependsOn.map((other) => ({ kind: 'model', key: other })),
    })
    const problems = validateStructure({
        version: 1,
        resources: [model('a', ['b']), model('b', ['a']), model('c', ['gone'])],
    })
    assert.deepEqual(
        problems.map(({ code, key, path }) => [code, key, path]),
        [
            ['dependency_missing', 'c', 'depends_on[0]'],
            ['dependency_cycle', 'a', undefined],
        ]
    )
})

test('validating a saved description reports duplicates and names each source file', () => {
    const resource = { kind: 'insight', key: 'twice', body: { name: 'x' }, source: { file: 'views.ts' } }
    assert.deepEqual(tuples(validateStructure({ version: 1, resources: [resource, resource] })), [
        ['key_duplicate', 'error', 'insight', 'twice', undefined, 'views.ts'],
    ])
    const description = { version: 1, resources: [{ ...resource, body: { query: 3 } }] }
    assert.deepEqual(tuples(validateDescription(description, { validator })), [
        ['schema_invalid', 'error', 'insight', 'twice', 'query', 'views.ts'],
    ])
})

test('loads a TypeScript stack folder with extensionless imports and records each source file', async () => {
    const result = await loadStack(fixture('stack'), { root, validator })
    assert.deepEqual(result.problems, [])
    assert.deepEqual(
        result.description.resources.map(({ kind, key, source: from }) => [kind, key, from]),
        [
            ['alert', 'signup_drop', { file: 'tests/fixtures/stack/views.ts', export: 'signupDrop' }],
            ['dashboard', 'growth', { file: 'tests/fixtures/stack/views.ts', export: 'growth' }],
            ['insight', 'growth-signups', { file: 'tests/fixtures/stack/views.ts' }],
        ]
    )
})

test('source files are the same with source maps on, and in a folder with parentheses', () => {
    const copy = join(mkdtempSync(join(tmpdir(), 'stack (copy) ')), 'stack')
    temporary.push(dirname(copy))
    cpSync(fixture('stack'), copy, { recursive: true })
    const link = join(dirname(copy), 'node_modules', '@posthog')
    mkdirSync(link, { recursive: true })
    symlinkSync(root, join(link, 'sdk'))
    const script = `import { loadStack } from '@posthog/sdk/stack'
Error.stackTraceLimit = 1
const result = await loadStack(process.argv[1], { root: process.argv[2], skipSchemas: true })
console.log(JSON.stringify(result.description.resources.map((resource) => resource.source?.file ?? null)))`
    const run = (flags) =>
        JSON.parse(
            execFileSync(process.execPath, [...flags, '--input-type=module', '-e', script, copy, dirname(copy)], {
                cwd: root,
                encoding: 'utf8',
            })
        )
    const expected = ['stack/views.ts', 'stack/views.ts', 'stack/views.ts']
    assert.deepEqual(run([]), expected)
    assert.deepEqual(run(['--enable-source-maps']), expected)
})

test('a definition from outside the stack folder is reported, not collected', async () => {
    const result = await loadStack(fixture('stack-outside/main'), { root, validator })
    assert.deepEqual(
        result.description.resources.map(({ kind, key }) => `${kind}:${key}`),
        ['alert:watch']
    )
    assert.deepEqual(tuples(result.problems), [
        ['outside_stack', 'error', 'alert', 'watch', undefined, 'tests/fixtures/stack-outside/main/index.ts'],
    ])
})

test('a folder without an index reports it instead of throwing', async () => {
    const result = await loadStack(fixture('stack-outside'), { root, skipSchemas: true })
    assert.deepEqual(
        result.problems.map((problem) => problem.code),
        ['entry_missing']
    )
})

test('the all-kinds fixture evaluates to its description.json, with no problems', async () => {
    const result = await loadStack(fixture('stack-all-kinds'), { validator })
    assert.deepEqual(result.problems, [])
    const committed = JSON.parse(readFileSync(join(fixture('stack-all-kinds'), 'description.json'), 'utf8'))
    assert.deepEqual(result.description, committed)
})

// A project folder with this package's TypeScript, a tsconfig and one index.ts.
function project(tsconfig, files) {
    const folder = mkdtempSync(join(tmpdir(), 'stack-types-'))
    temporary.push(folder)
    mkdirSync(join(folder, 'node_modules'))
    const typescript = dirname(createRequire(import.meta.url).resolve('typescript/package.json'))
    symlinkSync(typescript, join(folder, 'node_modules', 'typescript'))
    writeFileSync(
        join(folder, 'tsconfig.json'),
        JSON.stringify({
            compilerOptions: {
                strict: true,
                module: 'ESNext',
                moduleResolution: 'bundler',
                skipLibCheck: true,
                ...tsconfig,
            },
        })
    )
    for (const [name, contents] of Object.entries(files)) {
        mkdirSync(dirname(join(folder, name)), { recursive: true })
        writeFileSync(join(folder, name), contents)
    }
    return folder
}

for (const [name, tsconfig, files, expected] of [
    [
        'noCheck in the tsconfig does not hide a type error',
        { noCheck: true },
        { 'index.ts': 'export const n: number = "free"\n' },
        ['failed', ['type_error']],
    ],
    [
        'a project that declares isolated declarations passes',
        { declaration: true, isolatedDeclarations: true },
        { 'index.ts': 'export const n: number = 1\n' },
        ['passed', []],
    ],
    [
        'an import through tsconfig paths is reported',
        { paths: { '~/*': ['./lib/*'] } },
        { 'index.ts': "export { n } from '~/value'\n", 'lib/value.ts': 'export const n = 1\n' },
        ['failed', ['import_unsupported']],
    ],
]) {
    test(`type check: ${name}`, async () => {
        const folder = project(tsconfig, files)
        const result = await typeCheckStack(folder, { root: folder })
        assert.deepEqual([result.status, result.problems.map((problem) => problem.code)], expected)
    })
}

test('type check: a folder without a compiler says it skipped, and why', async () => {
    const folder = mkdtempSync(join(tmpdir(), 'stack-no-types-'))
    temporary.push(folder)
    writeFileSync(join(folder, 'index.ts'), 'export {}\n')
    const result = await typeCheckStack(folder, { root: folder })
    assert.deepEqual(
        [result.status, result.reason, result.problems],
        [
            'skipped',
            'This project has no usable TypeScript compiler. Add typescript as a dev dependency to check types.',
            [],
        ]
    )
})
