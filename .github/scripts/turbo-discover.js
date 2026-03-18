#!/usr/bin/env node

// Discovers which products need testing and builds a GitHub Actions matrix.
//
// Isolation detection: products that declare a backend:contract-check script
// (with narrowed inputs in their own turbo.json) are considered isolated —
// they can be tested alone when only their non-contract files change.
// Products without contract-check are non-isolated: any change in them
// triggers the full test suite (all products + Django).
//
// Products under SMALL_THRESHOLD duration get grouped into one matrix entry
// to avoid spinning up a full Docker stack for a handful of tests.
// Durations come from .test_durations (maintained by pytest-split).
//
// Input:  LEGACY_CHANGED env var ("true"/"false")
// Output: JSON on stdout: { matrix, run_legacy }
//         Diagnostics on stderr

const { execSync } = require('child_process')
const fs = require('fs')

const SMALL_THRESHOLD_SECONDS = 2 * 60
const TARGET_SHARD_SECONDS = 10 * 60
// Per-product overhead not captured by .test_durations: turbo dispatch, pytest
// collection, Django init. First product pays ~45s, subsequent ~15s; use 60s
// as a conservative average. Durations also underpredict by ~2x because
// pytest-split data was collected under Django Core's shared session.
const SETUP_OVERHEAD_SECONDS = 60
const DURATION_SAFETY_FACTOR = 2
// Tests under these paths need special infrastructure (Temporal server, etc.)
// and are handled by Django CI's dedicated segments — exclude from duration estimates
const EXCLUDED_PATH_SEGMENTS = ['/temporal/']

const TURBO_EXEC_OPTS = { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], maxBuffer: 50 * 1024 * 1024 }

function parseTurboTasks(raw) {
    return JSON.parse(raw).tasks.filter((t) => !/NONEXISTENT/.test(t.command))
}

function packageToProduct(pkg) {
    return pkg.replace('@posthog/products-', '')
}

function getIsolatedProducts(contractTasks) {
    return new Set(contractTasks.map((t) => packageToProduct(t.package)))
}

function getMissProducts(testTasks) {
    return [
        ...new Set(testTasks.filter((t) => t.cache?.status === 'MISS').map((t) => packageToProduct(t.package))),
    ].sort()
}

function getAllProducts(testTasks) {
    return [...new Set(testTasks.map((t) => packageToProduct(t.package)))].sort()
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
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (test.startsWith(prefix) && !EXCLUDED_PATH_SEGMENTS.some((seg) => test.includes(seg))) {
            total += dur
        }
    }
    return total
}

function packSmallProducts(products, durations) {
    const buckets = []
    let current = []
    let currentDuration = 0

    for (const product of products) {
        const effective = getProductDuration(product, durations) * DURATION_SAFETY_FACTOR + SETUP_OVERHEAD_SECONDS
        if (current.length > 0 && currentDuration + effective > TARGET_SHARD_SECONDS) {
            buckets.push(current)
            current = []
            currentDuration = 0
        }
        current.push(product)
        currentDuration += effective
    }
    if (current.length > 0) {
        buckets.push(current)
    }
    return buckets
}

function buildMatrix(products, durations) {
    const matrix = []
    const small = []

    for (const product of products) {
        const duration = getProductDuration(product, durations)
        const shards = duration > TARGET_SHARD_SECONDS ? Math.ceil(duration / TARGET_SHARD_SECONDS) : 1
        console.error(`  ${product}: ${(duration / 60).toFixed(1)} min, ${shards} shard(s)`)
        const filters = `--filter=@posthog/products-${product}`

        if (duration < SMALL_THRESHOLD_SECONDS) {
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

    for (const bucket of packSmallProducts(small, durations)) {
        matrix.push({
            group: bucket.join(', '),
            filters: bucket.map((p) => `--filter=@posthog/products-${p}`).join(' '),
            pytest_args: '',
        })
    }

    return matrix
}

// --- Main ---

const legacyChanged = process.env.LEGACY_CHANGED === 'true'

let testTasks, contractTasks
try {
    // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
    testTasks = parseTurboTasks(execSync('./node_modules/.bin/turbo run backend:test --dry-run=json', TURBO_EXEC_OPTS))
    // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process
    contractTasks = parseTurboTasks(
        execSync('./node_modules/.bin/turbo run backend:contract-check --dry-run=json', TURBO_EXEC_OPTS)
    )
} catch (e) {
    console.error(`turbo dry-run failed: ${e.message}`)
    if (e.stderr) {
        console.error(e.stderr.toString().slice(0, 1000))
    }
    process.exit(1)
}
const isolatedProducts = getIsolatedProducts(contractTasks)
const allProducts = getAllProducts(testTasks)

console.error(`Isolated products (have contract-check): ${JSON.stringify([...isolatedProducts].sort())}`)

let products
let runLegacy

if (legacyChanged) {
    console.error('Legacy code changed — testing all products')
    products = allProducts
    runLegacy = true
} else {
    const missProducts = getMissProducts(testTasks)
    const nonIsolatedMisses = missProducts.filter((p) => !isolatedProducts.has(p))

    if (nonIsolatedMisses.length > 0) {
        // Non-isolated product changed — must test everything
        console.error(
            `Non-isolated products changed: ${JSON.stringify(nonIsolatedMisses)} — testing all products + Django`
        )
        products = allProducts
        runLegacy = true
    } else if (missProducts.length > 0) {
        // Only isolated products changed — check contract-check cache for those specific products
        const missProductSet = new Set(missProducts)
        const contractMisses = contractTasks
            .filter((t) => t.cache?.status === 'MISS')
            .map((t) => packageToProduct(t.package))
            .filter((p) => missProductSet.has(p))
        if (contractMisses.length > 0) {
            console.error(`Isolated product contracts changed: ${JSON.stringify(contractMisses)} — Django will run`)
            runLegacy = true
        } else {
            console.error('Only isolated product internals changed — Django can be skipped')
            runLegacy = false
        }
        products = missProducts
    } else {
        console.error('No product changes detected')
        products = []
        runLegacy = false
    }
}

console.error(`Products to test: ${JSON.stringify(products)}`)
console.error(`Run legacy (Django): ${runLegacy}`)

const durations = loadTestDurations()
const result = {
    matrix: buildMatrix(products, durations),
    run_legacy: runLegacy,
}
// eslint-disable-next-line no-console
process.stdout.write(JSON.stringify(result) + '\n')
