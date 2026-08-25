// Run with: node --test .github/scripts/turbo-discover-narrow.test.js
const { test } = require('node:test')
const assert = require('node:assert/strict')
const { narrowedProducts } = require('./turbo-discover')

const products = ['batch-exports', 'logs', 'signals', 'tasks', 'warehouse-sources']
const selection = (extra) => ({ ast: { full_run_reasons: [] }, combined: { products: [] }, ...extra })

test('keeps the must-run set plus what the selector reached, in product directory form', () => {
    const sel = selection({ combined: { products: ['warehouse_sources', 'logs'] } })
    assert.deepEqual(narrowedProducts(products, ['tasks'], sel), ['logs', 'tasks', 'warehouse-sources'])
})

test('a selector full-run signal keeps the full matrix', () => {
    const sel = selection({ ast: { full_run_reasons: ['posthog/settings/base.py is a full-run path'] } })
    assert.equal(narrowedProducts(products, ['tasks'], sel), null)
})

test('a missing or malformed selection keeps the full matrix', () => {
    assert.equal(narrowedProducts(products, ['tasks'], null), null)
    assert.equal(narrowedProducts(products, ['tasks'], { combined: { products: ['logs'] } }), null)
})

test('a selection that reaches no product runs only the must-run set, which may be nothing', () => {
    assert.deepEqual(narrowedProducts(products, ['signals'], selection()), ['signals'])
    assert.deepEqual(narrowedProducts(products, [], selection()), [])
})

test('products outside the matrix are ignored', () => {
    const sel = selection({ combined: { products: ['not_a_product'] } })
    assert.deepEqual(narrowedProducts(products, ['gone'], sel), [])
})
