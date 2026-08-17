// Run with: node --test .github/scripts/turbo-discover-product-durations.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { getProductDuration } = require('./turbo-discover')

const testDurations = {
    'products/tasks/backend/tests/test_one.py::test_one': 0.04,
    'products/tasks/backend/tests/test_two.py::test_two': 0.06,
    'products/workflows/backend/tests/test_workflow.py::test_run': 20,
}

test('prefers the raw per-product total', () => {
    assert.equal(getProductDuration('tasks', testDurations, { tasks: 1000 }), 1000)
})

test('falls back when the product has no raw total', () => {
    assert.equal(getProductDuration('workflows', testDurations, { tasks: 1000 }), 20)
})

test('falls back when the raw totals file is unavailable', () => {
    assert.equal(getProductDuration('tasks', testDurations, null), 0.1)
})
