#!/usr/bin/env node

// Discovers which products need testing and builds a GitHub Actions matrix.
//
// Isolation detection: products that declare a backend:contract-check script
// (with narrowed inputs in their own turbo.json) are considered isolated —
// they can be tested alone when only their non-contract files change.
// Products changed by Turbo's Git affectedness query are selected for product tests.
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

const { execFileSync } = require('child_process')
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
const TURBO_BIN = './node_modules/.bin/turbo'

function runTurbo(args) {
    return execFileSync(TURBO_BIN, args, TURBO_EXEC_OPTS)
}

function parseTurboTasks(raw) {
    return JSON.parse(raw).tasks.filter((t) => !/NONEXISTENT/.test(t.command))
}

function parseAffectedTasks(raw) {
    return JSON.parse(raw).data.affectedTasks.items
}

function packageToProduct(pkg) {
    return pkg.replace('@posthog/products-', '')
}

function getIsolatedProducts(contractTasks) {
    return new Set(contractTasks.map((t) => packageToProduct(t.package)))
}

function getAffectedTaskProducts(tasks) {
    return [...new Set(tasks.map((t) => packageToProduct(t.package.name)))].sort()
}

function getAllProducts(testTasks) {
    return [...new Set(testTasks.map((t) => packageToProduct(t.package)))].sort()
}

function affectedArgs(taskName) {
    const args = ['query', 'affected', '--tasks', taskName]
    if (process.env.TURBO_SCM_BASE) {
        args.push('--base', process.env.TURBO_SCM_BASE)
    }
    if (process.env.TURBO_SCM_HEAD) {
        args.push('--head', process.env.TURBO_SCM_HEAD)
    }
    return args
}

function logAffectedReasons(label, tasks) {
    const reasons = {}
    for (const task of tasks) {
        const reason = task.reason?.__typename || 'Unknown'
        reasons[reason] = (reasons[reason] || 0) + 1
    }
    console.error(`${label} affected reasons: ${JSON.stringify(reasons)}`)
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

let allTestTasks, affectedTestTasks, affectedContractTasks, contractTasks
try {
    allTestTasks = parseTurboTasks(runTurbo(['run', 'backend:test', '--dry-run=json']))
    if (!legacyChanged) {
        console.error(`Turbo affected base: ${process.env.TURBO_SCM_BASE || '(default)'}`)
        console.error(`Turbo affected head: ${process.env.TURBO_SCM_HEAD || '(default)'}`)
        affectedTestTasks = parseAffectedTasks(runTurbo(affectedArgs('backend:test')))
        affectedContractTasks = parseAffectedTasks(runTurbo(affectedArgs('backend:contract-check')))
        contractTasks = parseTurboTasks(runTurbo(['run', 'backend:contract-check', '--dry-run=json']))
    }
} catch (e) {
    console.error(`turbo discovery failed: ${e.message}`)
    if (e.stderr) {
        console.error(e.stderr.toString().slice(0, 1000))
    }
    process.exit(1)
}
const allProducts = getAllProducts(allTestTasks)

let products
let runLegacy

if (legacyChanged) {
    console.error('Legacy code changed — testing all products')
    products = allProducts
    runLegacy = true
} else {
    const isolatedProducts = getIsolatedProducts(contractTasks)
    const affectedProducts = getAffectedTaskProducts(affectedTestTasks)
    const nonIsolatedAffectedProducts = affectedProducts.filter((p) => !isolatedProducts.has(p))

    console.error(`Isolated products (have contract-check): ${JSON.stringify([...isolatedProducts].sort())}`)
    console.error(`Affected products: ${JSON.stringify(affectedProducts)}`)
    logAffectedReasons('backend:test', affectedTestTasks)

    if (nonIsolatedAffectedProducts.length > 0) {
        // Non-isolated product changed — must test everything
        console.error(
            `Non-isolated products changed: ${JSON.stringify(nonIsolatedAffectedProducts)} — testing all products + Django`
        )
        products = allProducts
        runLegacy = true
    } else if (affectedProducts.length > 0) {
        // Only isolated products changed — check whether their contract surface was affected
        const affectedProductSet = new Set(affectedProducts)
        const affectedContracts = getAffectedTaskProducts(affectedContractTasks)
            .filter((p) => affectedProductSet.has(p))
        logAffectedReasons('backend:contract-check', affectedContractTasks)
        if (affectedContracts.length > 0) {
            console.error(`Isolated product contracts changed: ${JSON.stringify(affectedContracts)} — Django will run`)
            runLegacy = true
        } else {
            console.error('Only isolated product internals changed — Django can be skipped')
            runLegacy = false
        }
        products = affectedProducts
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
