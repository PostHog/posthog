// Run with: node --test .github/scripts/turbo-discover-cascade.test.js
//
// Unit tests for the dependent-cascade logic in turbo-discover.js:
// productGraphFromTachMap, tachDependents, loadTachModuleGraph, and the lib
// package import scan (libImportName, productsImportingModule,
// coreFilesImportingModule, getAffectedLibPackages). Uses a synthetic graph and
// a temp-dir tree throughout — never asserts against the real tach map or the
// real products/, which would turn into change-detector tests that break on
// every unrelated import.

const test = require('node:test')
const assert = require('node:assert/strict')

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
    productGraphFromTachMap,
    tachDependents,
    loadTachModuleGraph,
    getAffectedLibPackages,
    libImportName,
    productsImportingModule,
    coreFilesImportingModule,
} = require('./turbo-discover')

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

// --- Lib packages as cascade sources ---
//
// A lib package is a uv distribution, so tach reports imports of it as
// third-party and no consumer declares an edge to it. Its consumers are found by
// scanning for import statements instead.

function writeTree(files) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'turbo-discover-scan-'))
    for (const [relative, contents] of Object.entries(files)) {
        const full = path.join(root, relative)
        fs.mkdirSync(path.dirname(full), { recursive: true })
        fs.writeFileSync(full, contents)
    }
    return root
}

test('the import scan finds a product that imports the lib and ignores mentions that are not imports', () => {
    const root = writeTree({
        'foo/backend/x.py': 'from owners_yaml.resolver import OwnersResolver\n',
        'bar/backend/y.py': '# owners_yaml is mentioned here\nMESSAGE = "import owners_yaml"\n',
        'baz/backend/z.py': 'from owners_yaml_extra import y\n',
        'multi_word/backend/w.py': 'import owners_yaml\n',
    })
    try {
        assert.deepEqual(productsImportingModule('owners_yaml', root), ['foo', 'multi-word'])
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('the import scan reports the core files importing a lib, which is what forces Django to run', () => {
    const root = writeTree({
        'posthog/models/thing.py': 'import os\n',
        'ee/billing/thing.py': 'from owners_yaml.resolver import OwnersResolver\n',
        'common/util/thing.py': 'x = "owners_yaml"\n',
    })
    try {
        const dirs = ['posthog', 'ee', 'common'].map((d) => path.join(root, d))
        assert.deepEqual(coreFilesImportingModule('owners_yaml', dirs), [path.join(root, 'ee/billing/thing.py')])
        assert.deepEqual(coreFilesImportingModule('missing_module', dirs), [])
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('a lib change reaches both its importers and the products that depend on those importers', () => {
    const root = writeTree({ 'stamphog/backend/logic.py': 'from owners_yaml.resolver import OwnersResolver\n' })
    try {
        const direct = productsImportingModule('owners_yaml', root)
        assert.deepEqual(direct, ['stamphog'])
        const products = graph({ stamphog: [], downstream: ['stamphog'] })
        assert.deepEqual([...new Set([...direct, ...tachDependents(direct, products)])].sort(), [
            'downstream',
            'stamphog',
        ])
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

// The import name and the package name are independent (@posthog/owners-yaml ships
// owners_yaml), so the manifest declares it. A guess that nothing imports would
// scan clean and read as "no consumer to test", which is why a missing or
// malformed declaration throws instead.
test('the lib import name is read from the package manifest, and a manifest that does not declare one throws', () => {
    const root = writeTree({
        'owners/package.json': '{ "name": "@posthog/owners-yaml", "pythonImportName": "owners_yaml" }',
        'silent/package.json': '{ "name": "@posthog/silent" }',
        'bad/package.json': '{ "name": "@posthog/bad", "pythonImportName": "Not A Module" }',
    })
    try {
        assert.equal(libImportName(path.join(root, 'owners')), 'owners_yaml')
        assert.throws(() => libImportName(path.join(root, 'silent')), /pythonImportName/)
        assert.throws(() => libImportName(path.join(root, 'bad')), /pythonImportName/)
        assert.throws(() => libImportName(path.join(root, 'absent')), /could not read/)
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('affected lib packages carry the directory from the dry-run list, and products are not lib packages', () => {
    const testTasks = [
        { package: '@posthog/owners-yaml', directory: 'packages/owners-yaml' },
        { package: '@posthog/products-stamphog', directory: 'products/stamphog' },
    ]
    const affected = [{ package: { name: '@posthog/owners-yaml' } }, { package: { name: '@posthog/products-stamphog' } }]

    assert.deepEqual(getAffectedLibPackages(testTasks, affected), [
        { name: '@posthog/owners-yaml', directory: 'packages/owners-yaml' },
    ])
})

// The two turbo runs must agree on the package set: a source with no directory
// cannot be scanned, so dropping it silently would skip its consumers.
test('fail closed: an affected package missing from the dry-run list throws rather than being skipped', () => {
    assert.throws(
        () => getAffectedLibPackages([], [{ package: { name: '@posthog/owners-yaml' } }]),
        /has no directory/
    )
})
