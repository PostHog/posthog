#!/usr/bin/env node

// Discovers which products need testing and builds a GitHub Actions matrix.
//
// Products with < THRESHOLD tests get grouped into one matrix entry
// to avoid spinning up a full Docker stack for a handful of tests.
//
// Input:  LEGACY_CHANGED env var ("true"/"false")
// Output: JSON matrix on stdout, diagnostics on stderr

const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const SMALL_THRESHOLD = 50
const TARGET_SHARD_SECONDS = 10 * 60

function getTurboTasks() {
    try {
        // Call turbo directly to avoid pnpm wrapper noise on stdout
        // (pnpm can emit engine warnings like {"node":">=24"} that break JSON parsing)
        const raw = execSync('./node_modules/.bin/turbo run backend:test --dry-run=json', {
            encoding: 'utf-8',
            stdio: ['pipe', 'pipe', 'pipe'],
        })
        const parsed = JSON.parse(raw)
        return parsed.tasks.filter((t) => !/NONEXISTENT/.test(t.command))
    } catch (e) {
        console.error(`turbo dry-run failed: ${e.message}`)
        if (e.stderr) {
            console.error(e.stderr.toString().slice(0, 1000))
        }
        return []
    }
}

function getProducts(tasks, legacyChanged) {
    if (legacyChanged) {
        // Legacy code changed — all products must be tested
        return [...new Set(tasks.map((t) => t.package.replace('@posthog/products-', '')))]
    }
    // Only product files changed — test only cache MISSes
    return [
        ...new Set(
            tasks.filter((t) => t.cache?.status === 'MISS').map((t) => t.package.replace('@posthog/products-', ''))
        ),
    ]
}

// Skip temporal/ — those tests need a Temporal server (handled by Django CI's Temporal segment)
const SKIP_DIRS = new Set(['__pycache__', 'temporal'])

function countTestsInDir(dir) {
    let count = 0
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory() && !SKIP_DIRS.has(entry.name)) {
            count += countTestsInDir(full)
        } else if (entry.isFile() && entry.name.endsWith('.py')) {
            const content = fs.readFileSync(full, 'utf-8')
            const matches = content.match(/def test_/g)
            if (matches) {
                count += matches.length
            }
        }
    }
    return count
}

function countTests(product) {
    // Package names use hyphens (batch-exports) but directories use underscores (batch_exports)
    const dirName = product.replace(/-/g, '_')
    const testDir = path.join('products', dirName, 'backend', 'tests')
    if (!fs.existsSync(testDir)) {
        return 0
    }
    return countTestsInDir(testDir)
}

function loadTestDurations() {
    try {
        return JSON.parse(fs.readFileSync('.test_durations', 'utf-8'))
    } catch {
        console.error('Warning: .test_durations not found, sharding disabled')
        return null
    }
}

function getProductDuration(product, durations) {
    if (!durations) {
        return 0
    }
    const dirName = product.replace(/-/g, '_')
    const prefix = `products/${dirName}/`
    const temporalPrefix = `${prefix}backend/tests/temporal/`
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (test.startsWith(prefix) && !test.startsWith(temporalPrefix)) {
            total += dur
        }
    }
    return total
}

function buildMatrix(products, durations) {
    const matrix = []
    const small = []

    for (const product of products) {
        const count = countTests(product)
        const duration = getProductDuration(product, durations)
        const shards = duration > TARGET_SHARD_SECONDS ? Math.ceil(duration / TARGET_SHARD_SECONDS) : 1
        console.error(`  ${product}: ${count} tests, ${(duration / 60).toFixed(1)} min, ${shards} shard(s)`)
        const filters = `--filter=@posthog/products-${product}`

        if (count < SMALL_THRESHOLD) {
            small.push(product)
        } else if (shards > 1) {
            for (let i = 1; i <= shards; i++) {
                matrix.push({
                    group: `${product} (${i}/${shards})`,
                    filters,
                    pytest_args: `-- --splits ${shards} --group ${i} --splitting-algorithm duration_based_chunks`,
                })
            }
        } else {
            matrix.push({ group: product, filters, pytest_args: '' })
        }
    }

    if (small.length > 0) {
        matrix.push({
            group: small.join(', '),
            filters: small.map((p) => `--filter=@posthog/products-${p}`).join(' '),
            pytest_args: '',
        })
    }

    return matrix
}

const legacyChanged = process.env.LEGACY_CHANGED === 'true'
const tasks = getTurboTasks()
const products = getProducts(tasks, legacyChanged)
console.error(`Products to test: ${JSON.stringify(products)}`)

const durations = loadTestDurations()
const matrix = buildMatrix(products, durations)
console.log(JSON.stringify(matrix))
