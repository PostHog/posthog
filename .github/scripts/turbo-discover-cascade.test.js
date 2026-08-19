// Run with: node --test .github/scripts/turbo-discover-cascade.test.js
//
// Unit tests for the dependent-cascade logic in turbo-discover.js:
// parseTachModules, tachDependents, and the lib-package import scan
// (libPackageToModule, productsImportingModule, coreFilesImportingModule).
// Uses a synthetic graph and a temp-dir tree throughout — never asserts against
// the real tach.toml or the real products/, which would turn into
// change-detector tests that break on every unrelated dependency edit.

const test = require('node:test')
const assert = require('node:assert/strict')

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
    parseTachModules,
    parseTachDependents,
    tachDependents,
    checkInternalLibConsistency,
    internalLibDependents,
    libPackageToModule,
    internalLibPackageToModule,
    productsImportingModule,
    coreFilesImportingModule,
    buildMatrix,
} = require('./turbo-discover')

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

// Test selection must stay transitive by default: a change in c can break a's
// tests through b even though a never imports c. Only merge-queue lane
// assignment asks for one hop, so a flipped default here would silently
// under-test every contract change.
test('direct stops at the first hop while the default stays transitive', () => {
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
    assert.deepEqual(tachDependents(['c'], graph, { direct: true }), ['b'])
    assert.deepEqual(tachDependents(['c'], graph).sort(), ['a', 'b'])
})

test('direct dependents terminate on a cycle rather than walking it', () => {
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
path = "products.downstream"
depends_on = ["products.a"]
layer = "modules"
`
    const graph = parseTachModules(toml)
    assert.deepEqual(tachDependents(['b'], graph, { direct: true }), ['a'])
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

// tach.toml annotates facade-only edges with prose that names the tach block
// enforcing them, so a depends_on list can carry a `]` inside a comment. The
// scan for the list's closing bracket used to stop there and drop every entry
// below it, and the fail-closed check could not see it because that check
// discarded comments too.
test('a comment inside depends_on does not truncate the list', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = [
    "products.b",
    # Facade-only (enforced by c's [[interfaces]] block): a queues c's work.
    "products.c",
    "products.d", # direct import
]
layer = "modules"
`
    assert.deepEqual(parseTachModules(toml).get('a'), ['b', 'c', 'd'])
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

// --- Lib packages as cascade sources ---
//
// A lib package is a uv distribution, so tach reports imports of it as
// third-party and no consumer declares an edge to it. Its consumers are found
// by scanning for import statements instead.

function writePythonTree(files) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'turbo-discover-scan-'))
    for (const [relative, contents] of Object.entries(files)) {
        const full = path.join(root, relative)
        fs.mkdirSync(path.dirname(full), { recursive: true })
        fs.writeFileSync(full, contents)
    }
    return root
}

test('the import scan finds a product that imports the lib and ignores mentions that are not imports', () => {
    const root = writePythonTree({
        'foo/backend/x.py': 'from posthog_owners.resolver import team_channel\n',
        'bar/backend/y.py': '# posthog_owners is mentioned here\nMESSAGE = "import posthog_owners"\n',
        'baz/backend/z.py': 'from posthog_owners_extra import y\n',
        'multi_word/backend/w.py': 'import posthog_owners\n',
    })
    try {
        assert.deepEqual(productsImportingModule('posthog_owners', root), ['foo', 'multi-word'])
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('the import scan reports the core files importing a lib, which is what forces Django to run', () => {
    const root = writePythonTree({
        'posthog/models/thing.py': 'import os\n',
        'ee/billing/thing.py': 'from posthog_owners.resolver import OwnersResolver\n',
        'common/util/thing.py': 'x = "posthog_owners"\n',
    })
    try {
        const dirs = ['posthog', 'ee', 'common'].map((d) => path.join(root, d))
        assert.deepEqual(coreFilesImportingModule('posthog_owners', dirs), [path.join(root, 'ee/billing/thing.py')])
        assert.deepEqual(coreFilesImportingModule('posthog_missing', dirs), [])
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('a lib change reaches both its importers and the products that depend on those importers', () => {
    const toml = `
[[modules]]
path = "products.stamphog"
depends_on = ["posthog"]
layer = "modules"

[[modules]]
path = "products.downstream"
depends_on = ["products.stamphog"]
layer = "modules"
`
    const root = writePythonTree({ 'stamphog/backend/logic.py': 'from posthog_owners.resolver import team_channel\n' })
    try {
        const direct = productsImportingModule('posthog_owners', root)
        assert.deepEqual(direct, ['stamphog'])
        const transitive = tachDependents(direct, parseTachModules(toml))
        assert.deepEqual([...new Set([...direct, ...transitive])].sort(), ['downstream', 'stamphog'])
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('lib package names map to their Python module, with dashes becoming underscores', () => {
    assert.equal(libPackageToModule('@posthog/owners'), 'posthog_owners')
    assert.equal(libPackageToModule('@posthog/code-review'), 'posthog_code_review')
})

test('fail closed: a package name outside the @posthog/<name> convention throws rather than inventing a module', () => {
    assert.throws(() => libPackageToModule('owners'), /@posthog/)
    assert.throws(() => libPackageToModule('@posthog/'), /@posthog/)
    assert.throws(() => libPackageToModule('@acme/owners'), /@posthog/)
    assert.throws(() => libPackageToModule('@posthog/Owners'), /@posthog/)
})

// --- Internal libs (posthog/libs/<name>) as cascade sources ---
//
// An internal lib is a tach module, so its consumers are declared in tach.toml
// and enforced by `tach check`. The cascade reads those declarations instead of
// scanning imports, and it has to see consumers outside products/ too, which
// the product graph deliberately drops.

test('internal lib package names map to their tach module, with dashes becoming underscores', () => {
    assert.equal(internalLibPackageToModule('@posthog/lib-probe'), 'posthog.libs.probe')
    assert.equal(internalLibPackageToModule('@posthog/lib-slack-digest'), 'posthog.libs.slack_digest')
})

test('fail closed: a package name outside the @posthog/lib-<name> convention throws rather than inventing a module', () => {
    assert.throws(() => internalLibPackageToModule('@posthog/owners'), /@posthog\/lib-/)
    assert.throws(() => internalLibPackageToModule('@posthog/lib-'), /@posthog\/lib-/)
    assert.throws(() => internalLibPackageToModule('@acme/lib-probe'), /@posthog\/lib-/)
    assert.throws(() => internalLibPackageToModule('@posthog/lib-Probe'), /@posthog\/lib-/)
})

test('reverse edges cover every module path as written, products and core and libs alike', () => {
    const toml = `
[[modules]]
path = "<root>"
depends_on = []
layer = "modules"

[[modules]]
path = "posthog.libs.probe"
depends_on = []
layer = "modules"

[[modules]]
path = "posthog"
depends_on = ["posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "products.stamphog"
depends_on = ["posthog", "posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "posthog.libs.other"
depends_on = ["posthog.libs.probe"]
layer = "modules"
`
    const reverse = parseTachDependents(toml)
    assert.deepEqual(reverse.get('posthog.libs.probe').sort(), ['posthog', 'posthog.libs.other', 'products.stamphog'])
    assert.deepEqual(reverse.get('posthog'), ['products.stamphog'])
    assert.equal(reverse.has('posthog.libs.other'), false)
})

test('reverse edges survive a comment carrying a bracket inside depends_on', () => {
    const toml = `
[[modules]]
path = "products.a"
depends_on = [
    "posthog.libs.probe",
    # Facade-only (enforced by c's [[interfaces]] block): a queues c's work.
    "products.c",
]
layer = "modules"
`
    const reverse = parseTachDependents(toml)
    assert.deepEqual(reverse.get('posthog.libs.probe'), ['products.a'])
    assert.deepEqual(reverse.get('products.c'), ['products.a'])
})

test('an internal lib reaches its declared product consumers as dashed product ids', () => {
    const toml = `
[[modules]]
path = "posthog.libs.probe"
depends_on = []
layer = "modules"

[[modules]]
path = "products.data_warehouse"
depends_on = ["posthog.libs.probe"]
layer = "modules"
`
    const result = internalLibDependents(['posthog.libs.probe'], parseTachDependents(toml))
    assert.deepEqual(result, { products: ['data-warehouse'], core: [], libs: [] })
})

test('a lib depending on a lib is walked transitively, and the seed is not reported as its own dependent', () => {
    const toml = `
[[modules]]
path = "posthog.libs.probe"
depends_on = []
layer = "modules"

[[modules]]
path = "posthog.libs.middle"
depends_on = ["posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "posthog.libs.outer"
depends_on = ["posthog.libs.middle"]
layer = "modules"

[[modules]]
path = "products.stamphog"
depends_on = ["posthog.libs.outer"]
layer = "modules"
`
    const result = internalLibDependents(['posthog.libs.probe'], parseTachDependents(toml))
    assert.deepEqual(result.libs, ['posthog.libs.middle', 'posthog.libs.outer'])
    assert.deepEqual(result.products, ['stamphog'])
    assert.deepEqual(internalLibDependents(['posthog.libs.probe', 'posthog.libs.middle'], parseTachDependents(toml)).libs, ['posthog.libs.outer'])
})

test('a core dependent is reported by module path, which is what forces Django to run', () => {
    const toml = `
[[modules]]
path = "posthog.libs.probe"
depends_on = []
layer = "modules"

[[modules]]
path = "posthog"
depends_on = ["posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "common.hogvm"
depends_on = ["posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "<root>"
depends_on = ["posthog.libs.probe"]
layer = "modules"
`
    const result = internalLibDependents(['posthog.libs.probe'], parseTachDependents(toml))
    assert.deepEqual(result.core, ['<root>', 'common.hogvm', 'posthog'])
    assert.deepEqual(result.products, [])
})

// Products and core are terminals: the product graph closes over product
// dependents separately, and a core dependent already means the full suite. A
// walk that continued through them would reach the whole repo from any lib.
test('the walk stops at products and core rather than continuing through them', () => {
    const toml = `
[[modules]]
path = "posthog.libs.probe"
depends_on = []
layer = "modules"

[[modules]]
path = "products.stamphog"
depends_on = ["posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "products.downstream"
depends_on = ["products.stamphog"]
layer = "modules"

[[modules]]
path = "posthog"
depends_on = ["posthog.libs.probe"]
layer = "modules"

[[modules]]
path = "ee"
depends_on = ["posthog"]
layer = "modules"
`
    const result = internalLibDependents(['posthog.libs.probe'], parseTachDependents(toml))
    assert.deepEqual(result.products, ['stamphog'])
    assert.deepEqual(result.core, ['posthog'])
})

// Half a declaration under-tests silently in both directions, so discovery
// fails instead of running with it.
test('a tach lib module with no workspace package throws, naming the package to add', () => {
    assert.throws(
        () => checkInternalLibConsistency(['posthog.libs.probe', 'posthog.libs.slack_digest'], ['posthog.libs.probe']),
        /tach module posthog\.libs\.slack_digest has no @posthog\/lib-slack-digest workspace package/
    )
})

test('a lib workspace package with no tach module throws, naming the module to add', () => {
    assert.throws(
        () => checkInternalLibConsistency(['posthog.libs.probe'], ['posthog.libs.probe', 'posthog.libs.slack_digest']),
        /workspace package @posthog\/lib-slack-digest has no posthog\.libs\.slack_digest module in tach\.toml/
    )
})

test('matching sets pass, including the case where the repo has no internal libs at all', () => {
    checkInternalLibConsistency(['posthog.libs.probe', 'posthog.libs.slack_digest'], ['posthog.libs.slack_digest', 'posthog.libs.probe'])
    checkInternalLibConsistency([], [])
})

test('internal libs get their own matrix entry, filtered by lib package rather than product package', () => {
    const matrix = buildMatrix([], null, ['posthog.libs.probe', 'posthog.libs.slack_digest'])
    assert.deepEqual(matrix, [
        { group: 'lib: probe', filters: '--filter=@posthog/lib-probe', pytest_args: '' },
        { group: 'lib: slack-digest', filters: '--filter=@posthog/lib-slack-digest', pytest_args: '' },
    ])
})
