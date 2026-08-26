// Run with: node --test .github/scripts/turbo-discover-selection.test.js
//
// Covers the backend test selection verdict: which Django tests run, how many shards
// they get, and which products stay in the matrix. All three read one decision, so a
// branch that regresses here silently changes what a PR is gated on.

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { decideSelection, narrowedProducts, selectedShards } = require('./turbo-discover')

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
            durations: { selected_seconds_by_segment: { core: 5000, poe: 0, temporal: 900 } },
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
