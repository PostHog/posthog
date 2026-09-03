// Run with: node --test .github/scripts/turbo-discover-cascade.test.js
//
// Unit tests for the dependent-cascade logic in turbo-discover.js:
// productGraphFromTachMap, tachDependents, loadTachModuleGraph. Uses a
// synthetic graph throughout — never asserts against the real tach map, which
// would turn into a change-detector test that breaks on every unrelated import.

const test = require('node:test')
const assert = require('node:assert/strict')

const { productGraphFromTachMap, tachDependents, loadTachModuleGraph } = require('./turbo-discover')

// Graph literals use the shape productGraphFromTachMap emits: product directory
// name -> sorted product directory names it imports.
const graph = (edges) => new Map(Object.entries(edges))

test('the file map collapses to a product graph: importers outside products/ and loose files under it are dropped, self-imports vanish, test importers count', () => {
    const fileMap = {
        'products/data_warehouse/backend/facade/api.py': [
            'products/data_modeling/backend/logic/models.py',
            'products/data_modeling/backend/test/test_models.py',
            'products/data_warehouse/backend/routes.py',
            'posthog/settings/web.py',
            'products/conftest.py',
        ],
        'products/lonely/backend/api.py': ['ee/api/wrapper.py'],
        'posthog/models/team.py': ['products/data_modeling/backend/logic/models.py'],
        'products/__init__.py': ['products/data_modeling/backend/apps.py'],
    }
    assert.deepEqual(
        productGraphFromTachMap(fileMap),
        graph({
            data_warehouse: [],
            data_modeling: ['data_warehouse'],
            lonely: [],
        })
    )
})

test('normalization round-trip: dashed input resolves against underscored directory names and returns dashed output', () => {
    const dependents = tachDependents(
        ['data-warehouse'],
        graph({ data_warehouse: [], data_modeling: ['data_warehouse'] })
    )
    assert.deepEqual(dependents.sort(), ['data-modeling'])
})

test('cycle safety: terminates and returns correct dependents with a 2-cycle and a 3-cycle present', () => {
    const cyclic = graph({ a: ['b'], b: ['a'], x: ['y'], y: ['z'], z: ['x'], downstream: ['z'] })

    assert.deepEqual(tachDependents(['a'], cyclic).sort(), ['b'])
    assert.deepEqual(tachDependents(['x'], cyclic).sort(), ['downstream', 'y', 'z'])
})

// Test selection must stay transitive by default: a change in c can break a's
// tests through b even though a never imports c. Only merge-queue lane
// assignment asks for one hop, so a flipped default here would silently
// under-test every contract change.
test('direct stops at the first hop while the default stays transitive', () => {
    const chain = graph({ a: ['b'], b: ['c'], c: [] })
    assert.deepEqual(tachDependents(['c'], chain, { direct: true }), ['b'])
    assert.deepEqual(tachDependents(['c'], chain).sort(), ['a', 'b'])
})

test('direct dependents terminate on a cycle rather than walking it', () => {
    assert.deepEqual(tachDependents(['b'], graph({ a: ['b'], b: ['a'], downstream: ['a'] }), { direct: true }), ['a'])
})

test("core is never a node: two products that only meet through posthog are not each other's dependents", () => {
    const fileMap = {
        'products/x/backend/api.py': ['posthog/api/router.py'],
        'posthog/api/router.py': ['products/y/backend/routes.py'],
    }
    const collapsed = productGraphFromTachMap(fileMap)
    assert.deepEqual(collapsed, graph({ x: [], y: [] }))
    assert.deepEqual(tachDependents(['x'], collapsed), [])
    assert.deepEqual(tachDependents(['y'], collapsed), [])
})

test('changed products are excluded from their own dependent set', () => {
    assert.deepEqual(tachDependents(['a', 'b'], graph({ a: ['b'], b: [] })), [])
})

// The callers widen on null and would crash on a throw, so a run that cannot
// start has to come back as "unknown", not as an exception. A repo root that
// does not exist fails the spawn before any real uv or tach is involved.
test('fail closed: a run that cannot start yields null instead of throwing', () => {
    assert.equal(loadTachModuleGraph('/nonexistent/repo-root'), null)
})
