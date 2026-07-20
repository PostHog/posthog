// Run with: node --test .github/scripts/turbo-discover-cascade.test.js
//
// Unit tests for the dependent-cascade logic in turbo-discover.js:
// parseTachModules, tachDependents. Uses a synthetic graph throughout —
// never asserts against the real tach.toml, which would turn into a
// change-detector test that breaks on every unrelated dependency edit.

const test = require('node:test')
const assert = require('node:assert/strict')

const { parseTachModules, tachDependents } = require('./turbo-discover')

test('normalization round-trip: dashed input resolves against underscored tach names and returns dashed output', () => {
    const toml = `
[[modules]]
path = "products.data_warehouse"
depends_on = [
    "posthog",
]
layer = "modules"

[[modules]]
path = "products.data_modeling"
depends_on = [
    "posthog",
    "products.data_warehouse",
]
layer = "modules"
`
    const graph = parseTachModules(toml)
    const dependents = tachDependents(['data-warehouse'], graph)
    assert.deepEqual(dependents.sort(), ['data-modeling'])
})

test('cycle safety: terminates and returns correct dependents with a 2-cycle and a 3-cycle present', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = ["products.b"]
layer = "modules"

[[modules]]
path = "products.b"
depends_on = ["products.a"]
layer = "modules"

[[modules]]
path = "products.x"
depends_on = ["products.y"]
layer = "modules"

[[modules]]
path = "products.y"
depends_on = ["products.z"]
layer = "modules"

[[modules]]
path = "products.z"
depends_on = ["products.x"]
layer = "modules"

[[modules]]
path = "products.downstream"
depends_on = ["products.z"]
layer = "modules"
`
    const graph = parseTachModules(toml)

    const abResult = tachDependents(['a'], graph)
    assert.deepEqual(abResult.sort(), ['b'])

    const xyzResult = tachDependents(['x'], graph)
    assert.deepEqual(xyzResult.sort(), ['downstream', 'y', 'z'])
})

test('transitive: a multi-hop change reaches dependents beyond the first hop', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = ["products.b"]
layer = "modules"

[[modules]]
path = "products.b"
depends_on = ["products.c"]
layer = "modules"

[[modules]]
path = "products.c"
depends_on = ["posthog"]
layer = "modules"
`
    const graph = parseTachModules(toml)
    const dependents = tachDependents(['c'], graph)
    assert.deepEqual(dependents.sort(), ['a', 'b'])
})

test('core is never a node: posthog/ee/<root> are excluded as keys and values, and closures never traverse through them', () => {
    const toml = `
[[modules]]
path = "<root>"
depends_on = []
layer = "modules"

[[modules]]
path = "ee"
depends_on = [
    "products.x",
]
layer = "modules"

[[modules]]
path = "posthog"
depends_on = [
    "ee",
    "products.x",
    "products.y",
]
layer = "modules"

[[modules]]
path = "products.x"
depends_on = ["posthog"]
layer = "modules"

[[modules]]
path = "products.y"
depends_on = ["posthog"]
layer = "modules"
`
    const graph = parseTachModules(toml)
    assert.equal(graph.has('posthog'), false)
    assert.equal(graph.has('ee'), false)
    assert.equal(graph.has('<root>'), false)
    for (const deps of graph.values()) {
        assert.ok(!deps.includes('posthog'))
        assert.ok(!deps.includes('ee'))
    }

    // x and y both only reach each other via posthog — not a real edge in the
    // product graph, so neither should show up as the other's dependent.
    assert.deepEqual(tachDependents(['x'], graph), [])
    assert.deepEqual(tachDependents(['y'], graph), [])
})

test('changed products are excluded from their own dependent set', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = ["products.b"]
layer = "modules"

[[modules]]
path = "products.b"
depends_on = ["posthog"]
layer = "modules"
`
    const graph = parseTachModules(toml)
    const dependents = tachDependents(['a', 'b'], graph)
    assert.deepEqual(dependents, [])
})

test('fail closed: a depends_on entry that is not a double-quoted string throws instead of silently dropping the edge', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = ['products.b']
layer = "modules"
`
    assert.throws(() => parseTachModules(toml), /depends_on/)
})

test('fail closed: a path that is not a double-quoted string throws instead of silently dropping the module', () => {
    const toml = `
[[modules]]
path = 'products.a'
depends_on = ["products.b"]
layer = "modules"
`
    assert.throws(() => parseTachModules(toml), /path/)
})

test('comments inside a depends_on list are tolerated, and a block without depends_on is skipped without error', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = [
    "products.b", # transitional edge
]
layer = "modules"

[[modules]]
path = "products.no_deps"
layer = "modules"
`
    const graph = parseTachModules(toml)
    assert.deepEqual(graph.get('a'), ['b'])
    assert.equal(graph.has('no_deps'), false)
})
