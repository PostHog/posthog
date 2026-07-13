// Run with: node --test .github/scripts/turbo-discover-staleness.test.js
//
// Unit tests for the staleness detection logic in turbo-discover.js:
// collectTestFiles, checkProductStaleness, productPrefix, productEffectiveCost.

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('fs')
const os = require('os')
const path = require('path')

const {
    collectTestFiles,
    checkProductStaleness,
    productPrefix,
    productEffectiveCost,
    STALENESS_COVERAGE_THRESHOLD,
    STALENESS_FALLBACK_SECONDS_PER_FILE,
} = require('./turbo-discover')

test('productPrefix converts dashes to underscores', () => {
    assert.equal(productPrefix('warehouse-sources'), 'products/warehouse_sources/')
    assert.equal(productPrefix('batch-exports'), 'products/batch_exports/')
    assert.equal(productPrefix('alerts'), 'products/alerts/')
})

test('collectTestFiles finds test_*.py and *_test.py recursively', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-'))
    try {
        fs.mkdirSync(path.join(root, 'sub'), { recursive: true })
        fs.writeFileSync(path.join(root, 'test_foo.py'), '')
        fs.writeFileSync(path.join(root, 'bar_test.py'), '')
        fs.writeFileSync(path.join(root, 'helper_utils.py'), '')
        fs.writeFileSync(path.join(root, 'test_no_ext.txt'), '')
        fs.writeFileSync(path.join(root, 'sub', 'test_nested.py'), '')

        const files = collectTestFiles(root).sort()
        assert.equal(files.length, 3)
        assert.ok(files.some((f) => f.endsWith('test_foo.py')))
        assert.ok(files.some((f) => f.endsWith('bar_test.py')))
        assert.ok(files.some((f) => f.endsWith(path.join('sub', 'test_nested.py'))))
    } finally {
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('collectTestFiles returns empty for non-existent directory', () => {
    assert.deepEqual(collectTestFiles('/nonexistent/path/xyz'), [])
})

test('checkProductStaleness: exactly 70% coverage is NOT stale (threshold is <)', () => {
    // Set up a temp product directory with 10 test files
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-threshold-'))
    const origCwd = process.cwd()
    try {
        process.chdir(root)
        const productDir = path.join(root, 'products', 'my_product', 'backend')
        fs.mkdirSync(productDir, { recursive: true })
        // Create 10 test files
        for (let i = 0; i < 10; i++) {
            fs.writeFileSync(path.join(productDir, `test_file${i}.py`), '')
        }

        // Build durations covering exactly 7/10 files (70%)
        const durations = {}
        for (let i = 0; i < 7; i++) {
            durations[`products/my_product/backend/test_file${i}.py::TestClass::test_method`] = 1.0
        }

        const result = checkProductStaleness('my-product', durations)
        assert.equal(result.stale, false, '70% coverage should NOT be stale (threshold is strict <)')
        assert.equal(result.fileCount, 10)
        assert.equal(result.coveredCount, 7)
        assert.equal(result.coverage, 0.7)
    } finally {
        process.chdir(origCwd)
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('checkProductStaleness: 69% coverage IS stale', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-below-'))
    const origCwd = process.cwd()
    try {
        process.chdir(root)
        const productDir = path.join(root, 'products', 'my_product', 'backend')
        fs.mkdirSync(productDir, { recursive: true })
        // Create 100 test files for clean percentage
        for (let i = 0; i < 100; i++) {
            fs.writeFileSync(path.join(productDir, `test_file${i}.py`), '')
        }

        // Cover only 69 of 100 files
        const durations = {}
        for (let i = 0; i < 69; i++) {
            durations[`products/my_product/backend/test_file${i}.py::TestClass::test_method`] = 1.0
        }

        const result = checkProductStaleness('my-product', durations)
        assert.equal(result.stale, true, '69% coverage should be stale')
        assert.equal(result.fileCount, 100)
        assert.equal(result.coveredCount, 69)
    } finally {
        process.chdir(origCwd)
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('checkProductStaleness: dash-to-underscore mapping works correctly', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-dash-'))
    const origCwd = process.cwd()
    try {
        process.chdir(root)
        const productDir = path.join(root, 'products', 'warehouse_sources', 'backend')
        fs.mkdirSync(productDir, { recursive: true })
        fs.writeFileSync(path.join(productDir, 'test_source.py'), '')

        // Duration key uses underscore (as stored in .test_durations)
        const durations = {
            'products/warehouse_sources/backend/test_source.py::TestSource::test_connect': 2.0,
        }

        const result = checkProductStaleness('warehouse-sources', durations)
        assert.equal(result.stale, false)
        assert.equal(result.coveredCount, 1)
    } finally {
        process.chdir(origCwd)
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('checkProductStaleness: durations with :: are correctly split to file path', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-split-'))
    const origCwd = process.cwd()
    try {
        process.chdir(root)
        const productDir = path.join(root, 'products', 'alerts', 'backend')
        fs.mkdirSync(productDir, { recursive: true })
        fs.writeFileSync(path.join(productDir, 'test_alerts.py'), '')

        // Multiple test entries from the same file
        const durations = {
            'products/alerts/backend/test_alerts.py::TestAlerts::test_create': 0.5,
            'products/alerts/backend/test_alerts.py::TestAlerts::test_delete': 0.3,
            'products/alerts/backend/test_alerts.py::TestAlertsAPI::test_list': 1.0,
        }

        const result = checkProductStaleness('alerts', durations)
        assert.equal(result.stale, false)
        assert.equal(result.fileCount, 1)
        assert.equal(result.coveredCount, 1)
    } finally {
        process.chdir(origCwd)
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('checkProductStaleness: scans entire product dir including dags/', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-dags-'))
    const origCwd = process.cwd()
    try {
        process.chdir(root)
        const backendDir = path.join(root, 'products', 'my_product', 'backend')
        const dagsDir = path.join(root, 'products', 'my_product', 'dags')
        fs.mkdirSync(backendDir, { recursive: true })
        fs.mkdirSync(dagsDir, { recursive: true })
        fs.writeFileSync(path.join(backendDir, 'test_main.py'), '')
        fs.writeFileSync(path.join(dagsDir, 'test_dag.py'), '')

        // Only cover the backend file
        const durations = {
            'products/my_product/backend/test_main.py::Test::test_it': 1.0,
        }

        const result = checkProductStaleness('my-product', durations)
        // 1/2 files covered = 50% < 70% → stale
        assert.equal(result.stale, true)
        assert.equal(result.fileCount, 2)
        assert.equal(result.coveredCount, 1)
    } finally {
        process.chdir(origCwd)
        fs.rmSync(root, { recursive: true, force: true })
    }
})

test('checkProductStaleness: early returns include coverage field', () => {
    const noDurations = checkProductStaleness('any-product', null)
    assert.equal(noDurations.coverage, 0)
    assert.equal(noDurations.stale, true)

    // Product with no test files (nonexistent dir)
    const noFiles = checkProductStaleness('nonexistent-product', { 'some/path.py::test': 1.0 })
    assert.equal(noFiles.coverage, 0)
    assert.equal(noFiles.stale, false)
})

test('productEffectiveCost uses staleness fallback when coverage is poor', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'staleness-cost-'))
    const origCwd = process.cwd()
    try {
        process.chdir(root)
        const productDir = path.join(root, 'products', 'big_product', 'backend')
        fs.mkdirSync(productDir, { recursive: true })
        // Create 50 test files
        for (let i = 0; i < 50; i++) {
            fs.writeFileSync(path.join(productDir, `test_file${i}.py`), '')
        }

        // Cover only 10/50 = 20% (stale)
        const durations = {}
        for (let i = 0; i < 10; i++) {
            durations[`products/big_product/backend/test_file${i}.py::Test::test`] = 0.5
        }

        const cost = productEffectiveCost('big-product', durations)
        // Fallback: max(5.0 duration, 50 * 5) = 250s → 250 * 1.3 + 60 = 385
        const expectedBase = 50 * STALENESS_FALLBACK_SECONDS_PER_FILE
        assert.ok(cost > expectedBase, `cost ${cost} should exceed fallback base ${expectedBase}`)
    } finally {
        process.chdir(origCwd)
        fs.rmSync(root, { recursive: true, force: true })
    }
})
