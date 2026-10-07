// Run with: node --test .github/scripts/turbo-discover-core-scope.test.js
//
// Unit tests for how turbo-discover.js runs a product without its core tests. A wrong
// ignore list fails in one direction only: it skips tests the diff can break and the
// job stays green. These tests pin which products are scoped and what they ignore.

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { ignorePathsFor, resolveCoreScopes, buildMatrix } = require('./turbo-discover.js')

const CORE_TESTS = ['backend/tests/test_api.py', 'backend/sources/common/test_base.py', 'backend/sources/test_registry.py']
const LEAF_TESTS = ['backend/sources/acme/tests/test_acme.py', 'backend/sources/tests/test_catalog.py']

test('ignorePathsFor ignores a core-only directory whole and never an ancestor of a leaf test', () => {
    assert.deepEqual(ignorePathsFor(CORE_TESTS, LEAF_TESTS), [
        'backend/sources/common',
        'backend/sources/test_registry.py',
        'backend/tests',
    ])
})

function productWithTests(files) {
    const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'core-scope-'))
    const productDir = path.join(repoRoot, 'products', 'catalog')
    for (const file of files) {
        fs.mkdirSync(path.dirname(path.join(productDir, file)), { recursive: true })
        fs.writeFileSync(path.join(productDir, file), '')
    }
    return productDir
}

function coreTask(directory, coreFiles) {
    return {
        package: '@posthog/products-catalog',
        directory,
        inputs: Object.fromEntries(coreFiles.map((file) => [file, 'hash'])),
    }
}

const affected = (product) => [{ package: { name: `@posthog/products-${product}` } }]

test('a changed product whose core is untouched ignores exactly its core tests', () => {
    const directory = productWithTests([...CORE_TESTS, ...LEAF_TESTS])
    const tasks = [coreTask(directory, [...CORE_TESTS, 'backend/models.py'])]

    const scopes = resolveCoreScopes(tasks, [], new Set(['catalog']))

    assert.deepEqual(scopes.get('catalog'), {
        ignores: ['backend/sources/common', 'backend/sources/test_registry.py', 'backend/tests'],
        coreTestCount: 3,
        leafTestCount: 2,
    })
})

test('a product keeps its whole suite when its core changed or a cascade pulled it in', () => {
    const directory = productWithTests([...CORE_TESTS, ...LEAF_TESTS])
    const tasks = [coreTask(directory, CORE_TESTS)]

    assert.equal(resolveCoreScopes(tasks, affected('catalog'), new Set(['catalog'])).size, 0)
    assert.equal(resolveCoreScopes(tasks, [], new Set()).size, 0)
})

test('a product with no leaf test is not scoped, because the run would collect nothing', () => {
    const directory = productWithTests(CORE_TESTS)

    assert.equal(resolveCoreScopes([coreTask(directory, CORE_TESTS)], [], new Set(['catalog'])).size, 0)
})

test('a scoped product runs alone, with its ignores, sized by its leaf tests', () => {
    const scope = { ignores: ['backend/tests'], coreTestCount: 1, leafTestCount: 1 }
    const union = {
        // Enough core work to split the product four ways if it counted.
        'products/catalog/backend/tests/test_api.py::test_slow': 2400,
        'products/catalog/backend/sources/acme/tests/test_acme.py::test_fast': 30,
        'products/small_one/backend/test_s.py::test_s': 40,
    }

    const matrix = buildMatrix(['catalog', 'small-one'], union, true, new Map([['catalog', scope]]))

    assert.deepEqual(
        matrix.map((entry) => [entry.group, entry.filters, entry.pytest_args]),
        [
            ['catalog (leaf tests)', '--filter=@posthog/products-catalog', '-- --ignore=backend/tests'],
            ['small-one', '--filter=@posthog/products-small-one', ''],
        ]
    )
})
