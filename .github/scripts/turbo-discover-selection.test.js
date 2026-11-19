// Run with: node --test .github/scripts/turbo-discover-selection.test.js
//
// Covers the backend test selection verdict: which Django tests run, how many shards
// they get, and which products stay in the matrix. All three read one decision, so a
// branch that regresses here silently changes what a PR is gated on.

const { test } = require('node:test')
const assert = require('node:assert/strict')
const {
    decideJsonTargets,
    decideSelection,
    decideSelectionWithShadow,
    isDagsterOnlyLegacyEdit,
    narrowedProducts,
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
        ['non_isolated_product', ['products/tasks/backend/test/fixtures/run.json'], null],
        ['non_isolated_product', ['products/logs/backend/test/test_logs.jsonnd', 'products/logs/backend/test/test_api.py'], null],
        ['contract_cascade', ['products/logs/backend/test/test_logs.jsonnd', 'products/logs/backend/logic.py'], null],
        ['contract_cascade', ['products/logs/backend/facade/contracts.py'], 1],
        [
            'non_isolated_product',
            [
                'products/tasks/backend/tests/test_models.py',
                'products/tasks/backend/facade/api.py',
                'products/tasks/frontend/Tasks.tsx',
                'frontend/src/scenes/Home.tsx',
                'products/tasks/backend/AGENTS.md',
            ],
            1,
        ],
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

test('every product cascade phase selects, and one above the trusted phase reports a shadow selection', () => {
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
        [
            { productCascadePhase: 2, runLegacyReason: 'contract_cascade' },
            { mode: 'selected', skip_reason: '', would_trust_phase: 2, ...noShadow },
        ],
        [
            { productCascadePhase: 2, runLegacyReason: 'contract_cascade', selection: cascadeSelection({ snob: { status: 'error' } }) },
            { mode: 'full', skip_reason: 'selector_error', would_trust_phase: 2, ...noShadow },
        ],
        [{ productCascadePhase: 3 }, { mode: 'selected', skip_reason: '', would_trust_phase: 3, ...noShadow }],
        [
            { productCascadePhase: 3, selection: cascadeSelection({ ast: { full_run_reasons: ['conftest.py'] } }) },
            { mode: 'full', skip_reason: 'full_run_requested', would_trust_phase: 3, ...noShadow },
        ],
        [{ productCascadePhase: 3, trustedProductCascadePhase: 2 }, { ...shadowed, would_trust_phase: 3 }],
        [
            { productCascadePhase: 3, trustedProductCascadePhase: 2, selection: cascadeSelection({ ast: { full_run_reasons: ['conftest.py'] } }) },
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
            { mode: 'full', skip_reason: 'selector_error', would_trust_phase: 3, ...noShadow },
        ],
        [{ productCascadePhase: 1, draft: true, selection: null }, { mode: 'skip', skip_reason: 'selector_error', ...noShadow }],
        [{ productCascadePhase: 1, disabled: true }, { mode: 'full', skip_reason: 'disabled', ...noShadow }],
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
