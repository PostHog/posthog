// Run with: node --test .github/scripts/schema-impact.test.js
//
// Covers the pure pieces (diff, regex, product mapping) plus an end-to-end
// pass that writes a temporary product tree to verify the import scan.

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('fs')
const os = require('os')
const path = require('path')

const {
    diffDefinitions,
    extractImports,
    affectedProductsFor,
    buildImportMap,
    productFromPath,
} = require('./schema-impact')

const schema = (defs) => JSON.stringify({ $schema: 'x', definitions: defs })

test('diffDefinitions classifies added/removed/modified', () => {
    const base = schema({ A: { type: 'object', a: 1 }, B: { type: 'string' } })
    const head = schema({ A: { type: 'object', a: 2 }, C: { type: 'number' } })
    const { added, removed, modified } = diffDefinitions(base, head)
    assert.deepEqual(added, ['C'])
    assert.deepEqual(removed, ['B'])
    assert.deepEqual(modified, ['A'])
})

test('diffDefinitions: purely additive change has empty modified+removed', () => {
    const base = schema({ A: { type: 'object' } })
    const head = schema({ A: { type: 'object' }, NewType: { type: 'string' } })
    const { added, removed, modified } = diffDefinitions(base, head)
    assert.deepEqual(added, ['NewType'])
    assert.deepEqual(removed, [])
    assert.deepEqual(modified, [])
})

test('extractImports handles single-line imports', () => {
    const src = 'from posthog.schema import LogsQuery, HogQLFilters\n'
    assert.deepEqual(extractImports(src).sort(), ['HogQLFilters', 'LogsQuery'])
})

test('extractImports handles parenthesized multi-line imports', () => {
    const src = [
        'from posthog.schema import (',
        '    LogsQuery,',
        '    HogQLFilters,',
        '    TrendsQuery,',
        ')',
        '',
    ].join('\n')
    assert.deepEqual(extractImports(src).sort(), ['HogQLFilters', 'LogsQuery', 'TrendsQuery'])
})

test('extractImports strips "as" aliases', () => {
    const src = 'from posthog.schema import LogsQuery as LQ, HogQLFilters\n'
    assert.deepEqual(extractImports(src).sort(), ['HogQLFilters', 'LogsQuery'])
})

test('extractImports ignores inline comments inside parens', () => {
    const src = 'from posthog.schema import (\n    LogsQuery,  # noqa\n    HogQLFilters,\n)\n'
    assert.deepEqual(extractImports(src).sort(), ['HogQLFilters', 'LogsQuery'])
})

test('extractImports finds multiple import statements in one file', () => {
    const src = [
        'from posthog.schema import LogsQuery',
        '# ...',
        'def f():',
        '    pass',
        'from posthog.schema import TrendsQuery',
        '',
    ].join('\n')
    assert.deepEqual(extractImports(src).sort(), ['LogsQuery', 'TrendsQuery'])
})

test('productFromPath converts directory underscores to hyphens', () => {
    assert.equal(productFromPath('products/data_warehouse/backend/foo.py', 'products'), 'data-warehouse')
    assert.equal(productFromPath('products/logs/backend/x.py', 'products'), 'logs')
    assert.equal(productFromPath('products/web_analytics/backend/y.py', 'products'), 'web-analytics')
})

test('productFromPath returns null for paths outside productsRoot', () => {
    assert.equal(productFromPath('posthog/foo.py', 'products'), null)
})

test('affectedProductsFor unions products across all changed types', () => {
    const map = new Map([
        ['A', new Set(['logs'])],
        ['B', new Set(['logs', 'experiments'])],
        ['C', new Set(['surveys'])],
    ])
    assert.deepEqual(affectedProductsFor(['A', 'B'], map), ['experiments', 'logs'])
    assert.deepEqual(affectedProductsFor(['nonexistent'], map), [])
})

test('buildImportMap end-to-end on a fixture product tree', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'schema-impact-'))
    try {
        const a = path.join(root, 'product_a', 'backend')
        const b = path.join(root, 'product_b', 'backend')
        fs.mkdirSync(a, { recursive: true })
        fs.mkdirSync(b, { recursive: true })
        fs.writeFileSync(
            path.join(a, 'mod.py'),
            'from posthog.schema import LogsQuery, HogQLFilters\n'
        )
        fs.writeFileSync(
            path.join(b, 'mod.py'),
            'from posthog.schema import (\n    HogQLFilters,\n    TrendsQuery as TQ,\n)\n'
        )
        // Noise: file without the import should be ignored
        fs.writeFileSync(path.join(b, 'noise.py'), 'import os\n')

        const map = buildImportMap(root)
        assert.deepEqual([...map.get('LogsQuery')], ['product-a'])
        assert.deepEqual([...map.get('TrendsQuery')], ['product-b'])
        assert.deepEqual([...map.get('HogQLFilters')].sort(), ['product-a', 'product-b'])
        assert.equal(map.has('NeverImported'), false)
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})
