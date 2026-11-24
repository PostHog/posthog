// Run with: node --test .github/scripts/turbo-discover-selection.test.js
//
// Covers the backend test selection verdict: which Django tests run, how many shards
// they get, and which products stay in the matrix. All three read one decision, so a
// branch that regresses here silently changes what a PR is gated on.

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const {
    closeWatchedSets,
    productsReachedByFiles,
    decideJsonTargets,
    decideProductChange,
    decideSelection,
    decideSelectionWithShadow,
    deletedProductPythonFiles,
    isDagsterOnlyLegacyEdit,
    listChangedFiles,
    narrowedProducts,
    parseWatchedAnswer,
    productCascadePhase,
    productsWithUndeclaredInputChanges,
    selectedShards,
} = require('./turbo-discover')

const segments = (extra) => ({ core: [], poe: [], temporal: [], compat: [], ...extra })

const selectionFixture = (extra) => ({
    changed_file_count: 3,
    ast: { full_run_reasons: [] },
    combined: {
        count: 2,
        products: [],
        segments: segments({ core: ['posthog/models/test_a.py'] }),
    },
    durations: {
        total_seconds: 90000,
        selected_seconds: 120,
        skipped_seconds: 4500,
        selected_seconds_by_segment: { core: 0, poe: 0, temporal: 0 },
    },
    ...extra,
})

// A legacy-diff PR that the selector narrowed — the case every branch below departs from.
const decide = (overrides) =>
    decideSelection({
        applies: true,
        disabled: false,
        draft: false,
        legacyChanged: true,
        runLegacy: true,
        runLegacyReason: 'legacy_changed',
        selection: selectionFixture(),
        ...overrides,
    })

test('a run that does not select leaves an empty mode for every consumer to default on', () => {
    for (const overrides of [{ applies: false }, { runLegacy: false, runLegacyReason: '' }]) {
        const decision = decide(overrides)
        assert.equal(decision.mode, '')
        assert.equal(decision.narrowed, null)
        assert.equal(decision.segment_shards, null)
        assert.equal(decision.changed_file_count, null)
    }
})

test('a ready PR falls back to the full matrices and a draft skips them', () => {
    assert.equal(decide({ disabled: true }).mode, 'full')
    assert.equal(decide({ disabled: true, draft: true }).mode, 'skip')
})

test('each distrusted input has its own reason, so telemetry can tell them apart', () => {
    const cases = [
        [{ disabled: true }, 'disabled'],
        [{ runLegacyReason: 'contract_cascade' }, 'untrusted'],
        [{ runLegacyReason: 'schema' }, 'untrusted'],
        [{ selection: null }, 'selector_error'],
        [{ selection: selectionFixture({ ast: { full_run_reasons: ['posthog/settings/base.py'] } }) }, 'full_run_requested'],
        [{ selection: selectionFixture({ combined: { count: 0, products: [], segments: segments() } }) }, 'empty_selection'],
        [
            {
                dagsterOnlyLegacyEdit: true,
                selection: selectionFixture({
                    snob: { status: 'error' },
                    combined: { count: 0, products: [], segments: segments() },
                }),
            },
            'empty_selection',
        ],
        [{ selection: selectionFixture({ durations: { total_seconds: 0, selected_seconds: 0, skipped_seconds: 0 } }) }, 'no_durations'],
        [{ selection: selectionFixture({ durations: undefined }) }, 'no_durations'],
    ]
    for (const [overrides, reason] of cases) {
        const decision = decide(overrides)
        assert.equal(decision.skip_reason, reason)
        assert.equal(decision.narrowed, false)
        assert.equal(decision.mode, 'full')
        assert.equal(decision.core_files, '')
        assert.equal(decision.run_poe, false)
        assert.equal(decision.run_temporal, false)
    }
})

test('after a full run passed, a ready PR runs the subset unless the subset is absent or blind', () => {
    const requested = selectionFixture({ ast: { full_run_reasons: ['conftest.py'] }, snob: { status: 'ok' } })
    const cascade = (runLegacyReason, extra) => ({
        legacyChanged: false,
        runLegacyReason,
        selection: selectionFixture({ snob: { status: 'ok' } }),
        ...extra,
    })
    const cases = [
        [cascade('non_isolated_product'), 'selected', '', 'untrusted'],
        [cascade('contract_cascade', { selection: requested }), 'selected', '', 'untrusted'],
        [{ selection: requested }, 'selected', '', 'full_run_requested'],
        [cascade('schema'), 'full', 'untrusted', ''],
        [cascade('lib_cascade'), 'full', 'untrusted', ''],
        [cascade('contract_cascade', { selection: null }), 'full', 'untrusted', ''],
        [{ selection: selectionFixture({ combined: { count: 0, products: [], segments: segments() } }) }, 'full', 'empty_selection', ''],
        [{ disabled: true }, 'full', 'disabled', ''],
        [cascade('contract_cascade', { draft: true }), 'skip', 'untrusted', ''],
        [cascade('contract_cascade', { fullRunAlreadyPassed: false }), 'full', 'untrusted', ''],
    ]
    for (const [overrides, mode, skipReason, waivedReason] of cases) {
        const decision = decide({ fullRunAlreadyPassed: true, ...overrides })
        const label = JSON.stringify(overrides)
        assert.equal(decision.mode, mode, label)
        assert.equal(decision.skip_reason, skipReason, label)
        assert.equal(decision.waived_full_run_reason, waivedReason, label)
    }
})

test('the kill switch wins over a selection the selector was happy with', () => {
    // Ordered first on purpose: flipping it during an incident must not depend on why
    // the run would otherwise have been trusted.
    assert.equal(decide({ disabled: true, runLegacyReason: 'contract_cascade' }).skip_reason, 'disabled')
})

test('a fallback still reports the counts the selector produced', () => {
    const decision = decide({ selection: selectionFixture({ ast: { full_run_reasons: ['a', 'b'] } }) })
    assert.equal(decision.full_run_reasons_count, 2)
    assert.equal(decision.changed_file_count, 3)
    assert.equal(decision.selected_test_seconds, 120)
    assert.equal(decision.skipped_test_seconds, 4500)
})

test('a selected run hands each matrix leg its own file list', () => {
    const decision = decide({
        selection: selectionFixture({
            combined: {
                count: 4,
                products: [],
                segments: {
                    core: ['posthog/models/test_a.py', 'posthog/clickhouse/test_b.py'],
                    poe: ['posthog/clickhouse/test_b.py'],
                    temporal: ['posthog/temporal/tests/test_c.py'],
                    compat: ['posthog/clickhouse/test_b.py'],
                },
            },
            durations: { total_seconds: 90000, selected_seconds_by_segment: { core: 5000, poe: 0, temporal: 900 } },
        }),
    })

    assert.equal(decision.mode, 'selected')
    assert.equal(decision.narrowed, true)
    assert.equal(decision.skip_reason, '')
    assert.equal(decision.core_files, 'posthog/models/test_a.py posthog/clickhouse/test_b.py')
    assert.equal(decision.poe_files, 'posthog/clickhouse/test_b.py')
    assert.equal(decision.temporal_files, 'posthog/temporal/tests/test_c.py')
    assert.equal(decision.compat_files, 'posthog/clickhouse/test_b.py')
    assert.equal(decision.run_poe, true)
    assert.equal(decision.run_temporal, true)
    assert.deepEqual(decision.segment_shards, { core: 12, poe: 1, temporal: 2 })
})

test('a selection with no temporal file does not start the temporal leg', () => {
    const decision = decide()
    assert.equal(decision.mode, 'selected')
    assert.equal(decision.run_poe, false)
    assert.equal(decision.run_temporal, false)
    assert.equal(decision.temporal_files, '')
})

test('a Dagster-only legacy edit that selects no Django test runs no Django leg', () => {
    const decision = decide({
        dagsterOnlyLegacyEdit: true,
        selection: selectionFixture({
            snob: { status: 'ok' },
            combined: { count: 0, products: [], segments: segments() },
        }),
    })
    assert.equal(decision.mode, 'selected')
    assert.equal(decision.narrowed, true)
    assert.equal(decision.skip_reason, '')
    assert.equal(decision.core_files, '')
    assert.equal(decision.run_poe, false)
    assert.equal(decision.run_temporal, false)
})

test('only Dagster Python that still exists counts as a Dagster-only legacy edit', () => {
    const exists = (file) => !file.includes('deleted')
    const cases = [
        [['posthog/dags/backfill.py'], true],
        [['posthog/dags/backfill.py', 'posthog/dags/README.md', 'products/foo/backend/bar.py'], true],
        [['posthog/dags/backfill.py', 'posthog/models/team.py'], false],
        [['posthog/dags/schedule.yaml'], false],
        [['posthog/dags/deleted_job.py'], false],
        [undefined, false],
    ]
    for (const [changedFiles, expected] of cases) {
        assert.equal(isDagsterOnlyLegacyEdit(changedFiles, exists), expected, JSON.stringify(changedFiles))
    }
})

test('a product cascade gets the lowest phase that covers every file it changed', () => {
    const cases = [
        ['non_isolated_product', ['products/tasks/backend/tests/test_api.py'], 1],
        ['non_isolated_product', ['products/tasks/backend/tests/__snapshots__/test_api.ambr'], 1],
        ['non_isolated_product', ['products/tasks/backend/test/fixtures/run.json'], 3],
        ['non_isolated_product', ['products/tasks/backend/tests/test_api.py', 'products/warehouse_sources/backend/test/utils.py'], 3],
        ['non_isolated_product', ['products/tasks/backend/tests/conftest.py'], 3],
        ['non_isolated_product', ['products/tasks/backend/api_test.py'], 1],
        ['non_isolated_product', ['products/logs/backend/test/test_logs.jsonnd', 'products/logs/backend/test/test_api.py'], 3],
        ['contract_cascade', ['products/logs/backend/facade/contracts.py'], 2],
        [
            'non_isolated_product',
            [
                'products/tasks/backend/tests/test_models.py',
                'products/tasks/backend/facade/api.py',
                'products/tasks/frontend/Tasks.tsx',
                'frontend/src/scenes/Home.tsx',
                'products/tasks/backend/AGENTS.md',
            ],
            3,
        ],
        ['non_isolated_product', ['products/tasks/backend/tests/test_api.py', 'products/tasks/backend/facade/temporal_types.py'], 3],
        ['contract_cascade', ['products/logs/backend/logic.py'], 2],
        ['contract_cascade', ['products/logs/backend/migrations/0002_add_column.py'], 2],
        ['non_isolated_product', ['products/tasks/backend/logic.py', 'products/tasks/backend/tests/test_logic.py'], 3],
        ['non_isolated_product', ['products/tasks/backend/models.py'], null],
        ['non_isolated_product', ['products/tasks/backend/models/task.py'], null],
        ['non_isolated_product', ['products/tasks/backend/tests/test_api.py', 'products/tasks/backend/migrations/0042_x.py'], null],
        ['non_isolated_product', ['products/tasks/backend/tests/test_api.py', 'tach.toml'], null],
        ['contract_cascade', ['products/logs/backend/facade/api.py', 'packages/owners-yaml/owners_yaml/resolve.py'], null],
        ['non_isolated_product', ['products/isolation_baseline.txt'], null],
        ['non_isolated_product', ['products/tasks/frontend/Tasks.tsx'], 3],
        ['schema', ['products/tasks/backend/tests/test_api.py'], null],
        ['legacy_changed', ['products/tasks/backend/tests/test_api.py'], null],
        ['non_isolated_product', undefined, null],
    ]
    for (const [reason, changedFiles, phase] of cases) {
        assert.equal(productCascadePhase(reason, changedFiles), phase, `${reason} ${JSON.stringify(changedFiles)}`)
    }
})

const cascadeSelection = (extra) => selectionFixture({ snob: { status: 'ok' }, ...extra })

// A ready product-only PR: Django runs only because a product cascaded into it.
const decideCascade = (overrides) =>
    decideSelectionWithShadow({
        applies: true,
        disabled: false,
        draft: false,
        legacyChanged: false,
        runLegacy: true,
        runLegacyReason: 'non_isolated_product',
        selection: cascadeSelection(),
        ...overrides,
    })

test('only phase 1 product cascades select today, and the rest report a shadow selection', () => {
    const noShadow = { shadow_mode: '', shadow_skip_reason: '', shadow_selection_size: null }
    const shadowed = { mode: 'full', skip_reason: 'untrusted', shadow_mode: 'selected', shadow_skip_reason: '', shadow_selection_size: 1 }
    const cases = [
        [{ productCascadePhase: 1 }, { mode: 'selected', skip_reason: '', would_trust_phase: 1, ...noShadow }],
        [
            { productCascadePhase: 1, runLegacyReason: 'contract_cascade' },
            { mode: 'selected', skip_reason: '', would_trust_phase: 1, ...noShadow },
        ],
        [
            { productCascadePhase: 1, selection: cascadeSelection({ combined: { count: 0, products: [], segments: segments() } }) },
            { mode: 'selected', skip_reason: '', core_files: '', would_trust_phase: 1, ...noShadow },
        ],
        [{ productCascadePhase: 2, runLegacyReason: 'contract_cascade' }, { ...shadowed, would_trust_phase: 2 }],
        [{ productCascadePhase: 3 }, { ...shadowed, would_trust_phase: 3 }],
        [
            { productCascadePhase: 3, selection: cascadeSelection({ ast: { full_run_reasons: ['conftest.py'] } }) },
            { ...shadowed, would_trust_phase: 3, shadow_mode: 'full', shadow_skip_reason: 'full_run_requested', shadow_selection_size: null },
        ],
        [{ productCascadePhase: null }, { mode: 'full', skip_reason: 'untrusted', would_trust_phase: null, ...noShadow }],
        [
            { productCascadePhase: 1, runLegacyReason: 'schema' },
            { mode: 'full', skip_reason: 'untrusted', would_trust_phase: 1, shadow_mode: 'full', shadow_skip_reason: 'untrusted' },
        ],
        [
            { productCascadePhase: 1, selection: cascadeSelection({ ast: { full_run_reasons: ['products/tasks/backend/tests/conftest.py'] } }) },
            { mode: 'full', skip_reason: 'full_run_requested', would_trust_phase: 1, ...noShadow },
        ],
        [{ productCascadePhase: 1, selection: null }, { mode: 'full', skip_reason: 'selector_error', would_trust_phase: 1, ...noShadow }],
        [
            { productCascadePhase: 1, selection: cascadeSelection({ snob: { status: 'error' }, combined: { count: 0, products: [], segments: segments() } }) },
            { mode: 'full', skip_reason: 'selector_error', would_trust_phase: 1, ...noShadow },
        ],
        [
            { productCascadePhase: 3, selection: cascadeSelection({ snob: { status: 'error' } }) },
            { ...shadowed, would_trust_phase: 3, shadow_mode: 'full', shadow_skip_reason: 'selector_error', shadow_selection_size: null },
        ],
        [{ productCascadePhase: 1, draft: true, selection: null }, { mode: 'skip', skip_reason: 'selector_error', ...noShadow }],
        [{ productCascadePhase: 1, disabled: true }, { mode: 'full', skip_reason: 'disabled', ...noShadow }],
        [
            { productCascadePhase: 3, trustedProductCascadePhase: 3 },
            { mode: 'selected', skip_reason: '', would_trust_phase: 3, ...noShadow },
        ],
    ]
    for (const [overrides, expected] of cases) {
        const decision = decideCascade(overrides)
        for (const [key, value] of Object.entries(expected)) {
            assert.equal(decision[key], value, `${key} for ${JSON.stringify(overrides)}`)
        }
    }
})

test('a changed non-Python test input selects its own product', () => {
    const allProducts = new Set(['access-control', 'signals'])
    const cases = [
        [['products/access_control/backend/tests/__snapshots__/test_access_control.ambr'], ['access-control']],
        [['products/signals/skills/authoring-scouts/SKILL.md'], ['signals']],
        [['products/signals/backend/AGENTS.md'], []],
        [['products/signals/frontend/Scouts.tsx'], []],
        [['products/signals/backend/__pycache__/models.cpython-312.pyc'], []],
        [['products/unregistered/backend/fixtures/rows.json'], []],
        [['posthog/test/__snapshots__/test_team.ambr'], []],
    ]
    for (const [changedFiles, expected] of cases) {
        assert.deepEqual(
            productsWithUndeclaredInputChanges(changedFiles, allProducts),
            expected,
            JSON.stringify(changedFiles)
        )
    }
})

test('applies the full-matrix budget to the selected seconds of each segment', () => {
    // Work budget per shard is (target wall - segment overhead), same as the full
    // matrix: Core ceil(5000 / (720 - 295)) = 12, Temporal ceil(900 / (720 - 182)) = 2.
    // POE floors at 1 despite nothing selected.
    const selection = { durations: { selected_seconds_by_segment: { core: 5000, poe: 0, temporal: 900 } } }
    assert.deepEqual(selectedShards(selection), { core: 12, poe: 1, temporal: 2 })
})

test('shard counts floor at one, below the full-run minimum of three, and cap at the maximum', () => {
    const small = { durations: { selected_seconds_by_segment: { core: 30, poe: 30, temporal: 30 } } }
    assert.deepEqual(selectedShards(small), { core: 1, poe: 1, temporal: 1 })
    assert.equal(selectedShards({ durations: { selected_seconds_by_segment: { core: 10_000_000 } } }).core, 50)
})

test('shard counts degrade to one per segment on missing or malformed selector output', () => {
    for (const selection of [{}, { durations: {} }, { durations: { selected_seconds_by_segment: { core: 'wat' } } }]) {
        assert.deepEqual(selectedShards(selection), { core: 1, poe: 1, temporal: 1 })
    }
})

const products = ['batch-exports', 'logs', 'signals', 'tasks', 'warehouse-sources']

test('keeps the must-run set plus what the selector reached, in product directory form', () => {
    const selection = { combined: { products: ['warehouse_sources', 'logs'] } }
    assert.deepEqual(narrowedProducts(products, ['tasks'], selection), ['logs', 'tasks', 'warehouse-sources'])
})

test('a selection that reaches no product runs only the must-run set, which may be nothing', () => {
    assert.deepEqual(narrowedProducts(products, ['signals'], { combined: { products: [] } }), ['signals'])
    assert.deepEqual(narrowedProducts(products, [], { combined: { products: [] } }), [])
})

test('products outside the matrix are ignored', () => {
    const selection = { combined: { products: ['not_a_product'] } }
    assert.deepEqual(narrowedProducts(products, ['gone'], selection), [])
})

const JSON_TARGETS = [
    'posthog/hogql',
    'posthog/dags/tests/test_deletes.py',
    'posthog/tasks/test/test_usage_report.py',
    'products/batch_exports/backend/tests/test_hogql_source.py',
    'products/web_analytics/backend/hogql_queries',
]

const jsonTargets = (overrides) =>
    decideJsonTargets({
        targets: JSON_TARGETS,
        mode: 'selected',
        runLegacy: true,
        selectedTests: [],
        products: [],
        ...overrides,
    })

test('the events_json leg runs the whole list, a narrowed list, or nothing', () => {
    const cases = [
        [{ mode: '' }, null],
        [{ mode: 'full' }, null],
        [{ mode: 'skip' }, []],
        [
            { mode: '', skippedProducts: ['batch-exports'] },
            [
                'posthog/hogql',
                'posthog/dags/tests/test_deletes.py',
                'posthog/tasks/test/test_usage_report.py',
                'products/web_analytics/backend/hogql_queries',
            ],
        ],
        [
            {
                selectedTests: [
                    'posthog/hogql/test/test_query.py',
                    'posthog/hogql_queries/test/test_query_runner.py',
                    'posthog/api/test/test_team.py',
                    'products/web_analytics/backend/hogql_queries/test/test_stats_table.py',
                ],
                products: ['batch-exports'],
            },
            ['posthog/hogql/test/test_query.py', 'products/batch_exports/backend/tests/test_hogql_source.py'],
        ],
        [
            { selectedTests: ['posthog/hogql/test/test_query.py'], products: ['batch-exports'], draft: true },
            ['posthog/hogql/test/test_query.py'],
        ],
        [{ selectedTests: ['posthog/api/test/test_team.py'], products: ['logs'] }, []],
        [{ mode: '', runLegacy: false, products: ['surveys', 'web-analytics'] }, ['products/web_analytics/backend/hogql_queries']],
        [{ mode: '', runLegacy: false, products: ['surveys'] }, []],
        [
            { mode: 'full', skipReason: 'untrusted', runLegacyReason: 'non_isolated_product', diffProducts: ['web-analytics'] },
            ['products/web_analytics/backend/hogql_queries'],
        ],
        [{ mode: 'full', skipReason: 'untrusted', runLegacyReason: 'contract_cascade', diffProducts: ['tasks'] }, []],
        [{ mode: 'full', skipReason: 'untrusted', runLegacyReason: 'schema', diffProducts: ['tasks'] }, null],
        [{ mode: 'full', skipReason: 'disabled', runLegacyReason: 'non_isolated_product', diffProducts: ['tasks'] }, null],
        [{ mode: 'full', skipReason: 'untrusted', runLegacyReason: 'non_isolated_product', diffProducts: null }, null],
        [{ mode: 'full', doubled: true, products: ['batch-exports', 'web-analytics'] }, ['posthog/dags/tests/test_deletes.py']],
        [
            {
                mode: 'full',
                doubled: true,
                skipReason: 'untrusted',
                runLegacyReason: 'non_isolated_product',
                diffProducts: ['tasks'],
                products: ['batch-exports', 'web-analytics'],
            },
            ['posthog/dags/tests/test_deletes.py'],
        ],
        [{ mode: 'skip', doubled: true }, []],
        [{ mode: '', runLegacy: false, products: ['web-analytics'], doubled: true }, []],
        [{ doubled: true, selectedTests: ['posthog/hogql/test/test_query.py'], products: ['web-analytics'] }, []],
        [
            { doubled: true, selectedTests: ['posthog/dags/tests/test_deletes.py', 'posthog/hogql/test/test_query.py'] },
            ['posthog/dags/tests/test_deletes.py'],
        ],
    ]
    for (const [overrides, expected] of cases) {
        assert.deepEqual(jsonTargets(overrides), expected, JSON.stringify(overrides))
    }
})

// --- Isolation from hoglint's watched answer ---

// One answer in `hoglint watched`'s format 1: canvas claims the level and passes, tasks claims it
// and fails, and data_warehouse passes without a claim.
const watchedAnswer = (extra) =>
    JSON.stringify({
        format: 1,
        hoglint: '0.2.0',
        engine: 'native-0',
        policy: '0',
        level: 'isolated',
        complete: true,
        problems: [],
        groups: {
            canvas: {
                claimed: null,
                passes: true,
                reasons: [],
                watched: {
                    'products/canvas/backend/facade/api.py': 'structural: zone facade',
                    'products/canvas/backend/apps.py': 'wiring-watched: ...',
                },
            },
            tasks: { claimed: null, passes: false, reasons: ['has-facade: ...'], watched: {} },
        },
        ...extra,
    })

// No product claims the level: hoglint judges every one, and only a product that passes isolates.
test('only a product that passes the Isolated level is isolated', () => {
    const read = parseWatchedAnswer(watchedAnswer())
    assert.equal(read.status, 'ok')
    assert.deepEqual([...read.isolated], ['canvas'])
    assert.deepEqual([...read.watched.get('canvas')].sort(), [
        'products/canvas/backend/apps.py',
        'products/canvas/backend/facade/api.py',
    ])
    assert.match(read.digest, /^[0-9a-f]{16}$/)
})

// Each of these would otherwise read as "no watched file changed" and skip Django.
test('an answer hoglint could not complete, or one this script cannot read, isolates nothing', () => {
    const cases = [
        ['not json', 'unavailable'],
        [watchedAnswer({ format: 2 }), 'unavailable'],
        [JSON.stringify({ format: 1 }), 'unavailable'],
        [watchedAnswer({ groups: { canvas: { passes: true, watched: ['products/canvas/backend/facade/api.py'] } } }), 'unavailable'],
        [watchedAnswer({ groups: { canvas: { passes: true, watched: 'products/canvas/backend/facade/api.py' } } }), 'unavailable'],
        [watchedAnswer({ complete: false, problems: ['wiring-watched: cannot read every item of ...'] }), 'incomplete'],
    ]
    for (const [text, status] of cases) {
        const read = parseWatchedAnswer(text)
        assert.equal(read.status, status, text.slice(0, 60))
        assert.equal(read.isolated.size, 0, text.slice(0, 60))
    }
})

const ALL_PRODUCTS = ['canvas', 'error-tracking', 'tasks']

// A products-only diff reaching canvas, the one isolated product of the answer above.
const decideCanvas = (overrides) =>
    decideProductChange({
        affectedProducts: ['canvas'],
        allProducts: ALL_PRODUCTS,
        watched: parseWatchedAnswer(watchedAnswer()),
        changedFiles: ['products/canvas/backend/logic/layout.py'],
        deletedFiles: new Set(),
        direct: false,
        dependentsOf: () => ['error-tracking'],
        ...overrides,
    })

test('an isolated product skips Django only when the diff leaves its watched set alone', () => {
    const cases = [
        // An unwatched file: the product's own suite is enough.
        [{}, { products: ['canvas'], runLegacy: false, runLegacyReason: '' }],
        // A watched file: Django runs, with the products that depend on it.
        [
            { changedFiles: ['products/canvas/backend/facade/api.py'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // A deleted file is in no set of the head tree, so the deletion itself counts.
        [
            {
                changedFiles: ['products/canvas/backend/logic/old_layout.py'],
                deletedFiles: new Set(['products/canvas/backend/logic/old_layout.py']),
            },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // A backend data file can change what a core test sees, and Turbo's Python-only inputs
        // report no product for it.
        [
            { affectedProducts: [], changedFiles: ['products/canvas/backend/logic/seed.json'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // So can a data file outside backend/ that backend code reads, and a product package.json
        // or turbo.json changes what Turbo selects.
        [
            { affectedProducts: [], changedFiles: ['products/canvas/packages/canvas_builder/manifest.json'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        [
            { affectedProducts: [], changedFiles: ['products/canvas/package.json'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        [
            { affectedProducts: [], changedFiles: ['products/canvas/turbo.json'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // A fixture under the product's tests is no data file: the product's own suite reads it.
        [
            { affectedProducts: [], changedFiles: ['products/canvas/backend/tests/fixture.json'] },
            { products: ['canvas'], runLegacy: false, runLegacyReason: '' },
        ],
        // No base to diff against: nothing says the watched set was left alone.
        [
            { changedFiles: null },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // A selecting PR run takes direct dependents only; the queue walks them all.
        [
            {
                changedFiles: ['products/canvas/backend/facade/api.py'],
                direct: true,
                dependentsOf: (seeds, { direct }) => (direct ? ['error-tracking'] : ['error-tracking', 'tasks']),
            },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // Without the cascade the dependents are unknown.
        [
            { changedFiles: ['products/canvas/backend/facade/api.py'], dependentsOf: () => null },
            { products: ALL_PRODUCTS, runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
    ]
    for (const [overrides, expected] of cases) {
        const { products, runLegacy, runLegacyReason } = decideCanvas(overrides)
        assert.deepEqual({ products, runLegacy, runLegacyReason }, expected, JSON.stringify(overrides))
    }
})

// Core imports canvas's facade and its models; each goes on to import a logic file. A core test
// runs those logic files too, so a change to one must run Django.
test('a product file that outside code reaches through the product runs Django, and a missing map isolates nothing', () => {
    const fileMap = {
        'products/canvas/backend/facade/api.py': ['posthog/api/canvas.py'],
        'products/canvas/backend/models.py': ['posthog/models/test/test_canvas.py'],
        'products/canvas/backend/logic/layout.py': ['products/canvas/backend/facade/api.py'],
        'products/canvas/backend/logic/sizing.py': ['products/canvas/backend/models.py'],
        'products/canvas/backend/logic/unused.py': ['products/canvas/backend/tests/test_unused.py'],
    }
    const closed = closeWatchedSets(parseWatchedAnswer(watchedAnswer()), fileMap)
    const cases = [
        ['products/canvas/backend/logic/layout.py', true],
        ['products/canvas/backend/logic/sizing.py', true],
        ['products/canvas/backend/logic/unused.py', false],
    ]
    for (const [file, runLegacy] of cases) {
        assert.equal(decideCanvas({ watched: closed, changedFiles: [file] }).runLegacy, runLegacy, file)
    }
    const unread = closeWatchedSets(parseWatchedAnswer(watchedAnswer()), null)
    assert.equal(unread.status, 'unavailable')
    assert.equal(decideCanvas({ watched: unread }).runLegacyReason, 'watched_unavailable')
})

// Writes empty files at the given repo paths under a new temporary root, and returns the root.
const treeWith = (prefix, files) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
    for (const file of files) {
        fs.mkdirSync(path.join(root, path.dirname(file)), { recursive: true })
        fs.writeFileSync(path.join(root, file), '')
    }
    return root
}

// Python runs every package __init__.py above a module it imports, and what each one imports.
test('the package __init__.py files above a reached product file run Django, and what they import', () => {
    const root = treeWith('package-inits-', [
        'products/canvas/__init__.py',
        'products/canvas/backend/__init__.py',
        'products/canvas/backend/signals.py',
        'products/canvas/backend/logic/__init__.py',
        'products/canvas/backend/logic/queries.py',
        'products/canvas/backend/logic/unused.py',
    ])
    const fileMap = {
        'products/canvas/backend/logic/queries.py': ['posthog/models/organization.py'],
        'products/canvas/backend/signals.py': ['products/canvas/backend/__init__.py'],
    }
    const closed = closeWatchedSets(parseWatchedAnswer(watchedAnswer()), fileMap, root)
    const cases = [
        ['products/canvas/backend/logic/__init__.py', true],
        ['products/canvas/backend/__init__.py', true],
        ['products/canvas/__init__.py', true],
        ['products/canvas/backend/signals.py', true],
        ['products/canvas/backend/logic/unused.py', false],
    ]
    for (const [file, runLegacy] of cases) {
        assert.equal(decideCanvas({ watched: closed, changedFiles: [file] }).runLegacy, runLegacy, file)
    }
    fs.rmSync(root, { recursive: true, force: true })
})

// Turbo's affected query sees only a product's declared backend:test inputs, and a product's own
// turbo.json can narrow those, so a product file it reports no product for still reaches its product.
test('a changed product file reaches its product whatever Turbo reports, and frontend or test files skip Django', () => {
    const root = treeWith('product-root-', ['products/canvas/__init__.py', 'products/canvas/backend/facade/api.py'])
    const closed = closeWatchedSets(parseWatchedAnswer(watchedAnswer()), {}, root)
    fs.rmSync(root, { recursive: true, force: true })
    const cases = [
        // The product's root package runs before any of its modules.
        [
            { watched: closed, changedFiles: ['products/canvas/__init__.py'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        // A product turbo.json narrowed to its tests, with a watched edit Turbo no longer sees.
        [
            { changedFiles: ['products/canvas/turbo.json', 'products/canvas/backend/facade/api.py'] },
            { products: ['canvas', 'error-tracking'], runLegacy: true, runLegacyReason: 'contract_cascade' },
        ],
        [{ changedFiles: ['products/canvas/frontend/Canvas.tsx'] }, { products: [], runLegacy: false, runLegacyReason: '' }],
        [{ changedFiles: ['products/canvas/backend/AGENTS.md'] }, { products: [], runLegacy: false, runLegacyReason: '' }],
        [
            { changedFiles: ['products/canvas/backend/tests/test_layout.py'] },
            { products: ['canvas'], runLegacy: false, runLegacyReason: '' },
        ],
        [
            { changedFiles: ['products/canvas/backend/tests/__snapshots__/test_layout.ambr'] },
            { products: ['canvas'], runLegacy: false, runLegacyReason: '' },
        ],
    ]
    for (const [overrides, expected] of cases) {
        const { products, runLegacy, runLegacyReason } = decideCanvas({ affectedProducts: [], ...overrides })
        assert.deepEqual({ products, runLegacy, runLegacyReason }, expected, JSON.stringify(overrides.changedFiles))
    }
})

// Celery loads a product's task modules by name, so no import edge reaches them.
test('a change to a Celery task module of an isolated product runs Django', () => {
    const root = treeWith('tasks-', [
        'products/canvas/backend/tasks/__init__.py',
        'products/canvas/backend/tasks/sync.py',
        'products/canvas/backend/tasks/exports/__init__.py',
        'products/canvas/backend/tasks/exports/jobs.py',
        'products/canvas/backend/tasks/tests/test_sync.py',
    ])
    const closed = closeWatchedSets(parseWatchedAnswer(watchedAnswer()), {}, root)
    const cases = [
        ['products/canvas/backend/tasks/sync.py', true],
        ['products/canvas/backend/tasks/__init__.py', true],
        ['products/canvas/backend/tasks/exports/jobs.py', true],
        ['products/canvas/backend/tasks/tests/test_sync.py', false],
    ]
    for (const [file, runLegacy] of cases) {
        assert.equal(decideCanvas({ watched: closed, changedFiles: [file] }).runLegacy, runLegacy, file)
    }
    fs.rmSync(root, { recursive: true, force: true })
})

// Files directly under products/ run for every product, and settings read db_routing.yaml.
test('a change to a shared file directly under products/ runs every product and Django', () => {
    for (const file of ['products/__init__.py', 'products/conftest.py', 'products/db_routing.yaml']) {
        const { products, runLegacy, runLegacyReason } = decideCanvas({ affectedProducts: [], changedFiles: [file] })
        assert.deepEqual(
            { products, runLegacy, runLegacyReason },
            { products: ALL_PRODUCTS, runLegacy: true, runLegacyReason: 'products_root' },
            file
        )
    }
})

// A watched module that is a symlink runs its target, wherever the target lives.
test('a change to the target of a symlinked watched file runs Django', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'links-'))
    fs.mkdirSync(path.join(root, 'products/canvas/backend'), { recursive: true })
    fs.mkdirSync(path.join(root, 'products/canvas/frontend'), { recursive: true })
    fs.writeFileSync(path.join(root, 'products/canvas/frontend/_impl.py'), '')
    fs.symlinkSync('../frontend/_impl.py', path.join(root, 'products/canvas/backend/linked.py'))
    execFileSync('git', ['init', '-q'], { cwd: root })
    execFileSync('git', ['add', '.'], { cwd: root })
    const fileMap = { 'products/canvas/backend/linked.py': ['posthog/api/canvas.py'] }
    const closed = closeWatchedSets(parseWatchedAnswer(watchedAnswer()), fileMap, root)
    const target = 'products/canvas/frontend/_impl.py'
    // The selector loads hoglint's answer only for a diff that reaches a product, so the link must reach it.
    assert.deepEqual(productsReachedByFiles([target], ALL_PRODUCTS, root), ['canvas'])
    const previous = process.cwd()
    process.chdir(root)
    try {
        assert.equal(decideCanvas({ affectedProducts: [], watched: closed, changedFiles: [target] }).runLegacy, true)
    } finally {
        process.chdir(previous)
        fs.rmSync(root, { recursive: true, force: true })
    }
})

// Each case is an answer the diff cannot be judged by, so every product and Django run.
test('a missing answer, a failed level or a change to hoglint itself widens to every product', () => {
    const cases = [
        [{ watched: parseWatchedAnswer('not json') }, 'watched_unavailable'],
        [{ watched: parseWatchedAnswer(watchedAnswer({ complete: false })) }, 'watched_unavailable'],
        [{ affectedProducts: ['canvas', 'tasks'] }, 'non_isolated_product'],
        [{ changedFiles: ['products/canvas/backend/logic/layout.py', 'tools/hoglint/presets/posthog.toml'] }, 'watched_policy'],
        [{ changedFiles: ['products/canvas/backend/logic/layout.py', 'hoglint.toml'] }, 'watched_policy'],
        // A policy-only diff reaches no product, and still changes every watched set.
        [{ affectedProducts: [], watched: null, changedFiles: ['hoglint.toml'] }, 'watched_policy'],
        [{ affectedProducts: [], watched: null, changedFiles: ['tools/hoglint/presets/posthog.toml'] }, 'watched_policy'],
    ]
    for (const [overrides, reason] of cases) {
        const { products, runLegacy, runLegacyReason } = decideCanvas(overrides)
        assert.deepEqual({ products, runLegacy, runLegacyReason }, { products: ALL_PRODUCTS, runLegacy: true, runLegacyReason: reason }, reason)
    }
})

// git quotes a non-ASCII path in plain output ("products/canvas/backend/facade/pol\303\255cy.py").
// That string matches no watched file, so a change there would skip Django.
test('the diff lists a non-ASCII path as written, so it can match a watched file', () => {
    const changed = 'products/canvas/backend/facade/polícy.py'
    const deleted = 'products/canvas/backend/logic/cafés.py'
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'non-ascii-diff-'))
    const origCwd = process.cwd()
    const origBase = process.env.TURBO_SCM_BASE
    try {
        process.chdir(root)
        const git = (...args) => execFileSync('git', args, { encoding: 'utf-8' }).trim()
        git('init', '-q')
        git('config', 'user.email', 'test@example.com')
        git('config', 'user.name', 'test')
        git('config', 'commit.gpgsign', 'false')
        for (const file of [changed, deleted]) {
            fs.mkdirSync(path.dirname(file), { recursive: true })
            fs.writeFileSync(file, 'x = 1\n')
        }
        git('add', '.')
        git('commit', '-q', '-m', 'base')
        const base = git('rev-parse', 'HEAD')
        fs.writeFileSync(changed, 'x = 2\n')
        fs.rmSync(deleted)
        git('commit', '-q', '-am', 'head')

        assert.deepEqual(listChangedFiles(base, 'HEAD'), [changed, deleted])
        process.env.TURBO_SCM_BASE = base
        assert.deepEqual(deletedProductPythonFiles(), [deleted])
    } finally {
        process.chdir(origCwd)
        if (origBase === undefined) {
            delete process.env.TURBO_SCM_BASE
        } else {
            process.env.TURBO_SCM_BASE = origBase
        }
        fs.rmSync(root, { recursive: true, force: true })
    }
})
