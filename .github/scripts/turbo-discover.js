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
// Output: JSON on stdout: { matrix, run_legacy, django_shards }
//         Diagnostics on stderr

const { execFileSync } = require('child_process')
const fs = require('fs')

// --- Product shard sizing (same Amdahl shape as Django below) ---
// Each product is atomic for packing, but unlike Django the test pool isn't
// fungible across products — bin-pack products into target-sized shards, and
// multi-shard split any single product that overflows on its own.
const PRODUCT_TARGET_WALL_SECONDS = 10 * 60
// Per-product cost within a runner: turbo dispatch, pytest collection, Django
// init. First product pays ~45s, subsequent ~15s; use 60s as a conservative
// average that also absorbs the amortized portion of runner startup.
const PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS = 60
// Aligned with DJANGO_SAFETY_FACTOR below. Was 2x originally because pytest-
// split data was noisy under Django Core's shared session; the outlier-based
// merge produces cleaner numbers now.
const PRODUCT_SAFETY_FACTOR = 1.3
// Tests under these paths need special infrastructure (Temporal server, etc.)
// and are handled by Django CI's dedicated segments — exclude from duration estimates
const EXCLUDED_PATH_SEGMENTS = ['/temporal/']

// --- Django shard auto-sizing (Amdahl's law) ---
// wall_clock = overhead + (total_from_durations_file / shards)
//
// .test_durations has migration-inflated first-test durations corrected
// by optimize_test_durations.py (using JUnit to identify carriers and
// subtract the migration tax). Durations reflect actual test work.
//
// Per-segment overhead constants below cover the fixed per-shard cost
// outside test work: job setup, pytest collection, per-shard DB setup,
// per-segment infra. Measured from JUnit + job wall clocks on a recent
// run (lower bound — includes some per-test fixture setup that JUnit's
// junit_duration_report=call doesn't capture):
//   Core:     median 303s, max 591s   → 4 min covers it comfortably
//   CorePOE:  median 233s, max 280s   → 4 min has headroom
//   Temporal: median 375s, max 693s   → 6 min, temporal-server boot adds
//                                        meaningful fixed cost beyond Core
const DJANGO_OVERHEAD_SECONDS_BY_SEGMENT = {
    Core: 4 * 60,
    CorePOE: 4 * 60,
    Temporal: 6 * 60,
}
const DJANGO_TARGET_WALL_SECONDS = 20 * 60
const DJANGO_SAFETY_FACTOR = 1.3
const DJANGO_MIN_SHARDS = 3
const DJANGO_MAX_SHARDS = 50

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
    let parsed
    try {
        parsed = JSON.parse(fs.readFileSync('.test_durations', 'utf-8'))
    } catch {
        console.error('Warning: .test_durations not found, sharding disabled')
        return null
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        console.error('Warning: .test_durations is not a JSON object, sharding disabled')
        return null
    }
    // Strip non-finite values so a single corrupted entry can't NaN-poison the
    // matrix (Math.ceil(NaN) silently propagates through sort/compare, making
    // a product vanish from packing without an error).
    let dropped = 0
    for (const [k, v] of Object.entries(parsed)) {
        if (typeof v !== 'number' || !Number.isFinite(v)) {
            delete parsed[k]
            dropped++
        }
    }
    if (dropped > 0) {
        console.error(`Warning: dropped ${dropped} non-numeric entries from .test_durations`)
    }
    return parsed
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

function productEffectiveCost(product, durations) {
    return getProductDuration(product, durations) * PRODUCT_SAFETY_FACTOR + PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS
}

// First-fit-decreasing bin packing into TARGET-sized shards. Sorts products by
// effective cost descending so the largest products land first and small ones
// fill the gaps. Each bucket caps at PRODUCT_TARGET_WALL_SECONDS total.
function packProducts(products, durations) {
    const items = products
        .map((product) => ({ product, cost: productEffectiveCost(product, durations) }))
        .sort((a, b) => b.cost - a.cost)

    const buckets = []
    for (const { product, cost } of items) {
        let placed = false
        for (const bucket of buckets) {
            if (bucket.cost + cost <= PRODUCT_TARGET_WALL_SECONDS) {
                bucket.products.push(product)
                bucket.cost += cost
                placed = true
                break
            }
        }
        if (!placed) {
            buckets.push({ products: [product], cost })
        }
    }
    return buckets
}

// Path filters matching the Django workflow pytest invocations.
// Core: posthog/ + ee/ minus temporal, dags, hogvm
// Core POE: subset of Core (ignores hogql, hogql_queries) — same pool, fewer tests
// Temporal: posthog/temporal + products/batch_exports/backend/tests/temporal + products/tasks/backend/temporal
const DJANGO_SEGMENTS = {
    Core: {
        include: ['posthog/', 'ee/'],
        exclude: ['posthog/temporal/', 'posthog/dags/', 'common/hogvm/'],
    },
    CorePOE: {
        // Keep in sync with the person-on-events pytest targets in
        // ci-backend.yml's "Run Core tests" step.
        include: [
            'posthog/clickhouse/',
            'posthog/queries/',
            'products/product_analytics/backend/api/test/',
            'posthog/api/test/dashboards/test_dashboard.py',
            'ee/clickhouse/',
        ],
        exclude: ['posthog/temporal/', 'posthog/dags/', 'common/hogvm/', 'posthog/hogql_queries/', 'posthog/hogql/'],
    },
    Temporal: {
        include: ['posthog/temporal/', 'products/batch_exports/backend/tests/temporal/', 'products/tasks/backend/temporal/'],
        exclude: [],
    },
}

function getSegmentDuration(segment, durations) {
    if (!durations) return 0
    const { include, exclude } = DJANGO_SEGMENTS[segment]
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (!include.some((p) => test.startsWith(p))) continue
        if (exclude.some((p) => test.startsWith(p))) continue
        total += dur
    }
    return total
}

// Fallback shard counts used when .test_durations is missing.
const DJANGO_FALLBACK_SHARDS = { Core: 38, CorePOE: 7, Temporal: 7 }

function calculateShards(totalWorkSeconds, overheadSeconds) {
    const testBudget = DJANGO_TARGET_WALL_SECONDS - overheadSeconds
    if (testBudget <= 0) return DJANGO_MAX_SHARDS
    const shards = Math.ceil((totalWorkSeconds * DJANGO_SAFETY_FACTOR) / testBudget)
    return Math.max(DJANGO_MIN_SHARDS, Math.min(DJANGO_MAX_SHARDS, shards))
}

function buildDjangoShards(durations) {
    const result = {}
    for (const [segment] of Object.entries(DJANGO_SEGMENTS)) {
        const overhead = DJANGO_OVERHEAD_SECONDS_BY_SEGMENT[segment]
        const duration = getSegmentDuration(segment, durations)
        const shards = durations ? calculateShards(duration, overhead) : DJANGO_FALLBACK_SHARDS[segment]
        // calculateShards applies DJANGO_SAFETY_FACTOR — mirror it in the
        // wall estimate so the diagnostic matches the budget the shard count
        // actually targets (was previously under-reporting by ~30%).
        const wall = overhead + (duration * DJANGO_SAFETY_FACTOR) / shards
        result[segment] = { duration_seconds: duration, shards, estimated_wall_seconds: wall }
        const source = durations ? 'auto' : 'fallback'
        console.error(
            `  Django ${segment}: ${(duration / 60).toFixed(1)} min total, ${shards} shards (${source}), ~${(wall / 60).toFixed(1)} min est. wall`
        )
    }
    return result
}

function buildMatrix(products, durations) {
    const matrix = []
    const packable = []

    // Split a product across multiple shards only when its raw duration plus
    // one per-product overhead exceeds the target wall clock. Don't apply the
    // safety factor here — that inflation is for packing-capacity decisions
    // (avoid stuffing a bucket beyond budget under variance), not for the
    // "must we split?" check. Using the inflated cost for splitting causes
    // borderline products to fragment into uneven sub-shards (pytest-split
    // can't balance well when many tests have flat-default 0.01s values),
    // paying duplicate Docker setup for little parallel work gained.
    for (const product of products) {
        const raw = getProductDuration(product, durations) + PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS
        if (raw > PRODUCT_TARGET_WALL_SECONDS) {
            const shards = Math.ceil(raw / PRODUCT_TARGET_WALL_SECONDS)
            console.error(`  ${product}: ${(raw / 60).toFixed(1)} min raw → split across ${shards} shards`)
            const filters = `--filter=@posthog/products-${product}`
            for (let i = 1; i <= shards; i++) {
                matrix.push({
                    group: `${product} (${i}/${shards})`,
                    filters,
                    pytest_args: `-- --splits ${shards} --group ${i} --splitting-algorithm duration_based_chunks`,
                })
            }
        } else {
            packable.push(product)
        }
    }

    for (const bucket of packProducts(packable, durations)) {
        console.error(
            `  bucket (${(bucket.cost / 60).toFixed(1)} min effective): ${bucket.products.join(', ')}`
        )
        matrix.push({
            group: bucket.products.join(', '),
            filters: bucket.products.map((p) => `--filter=@posthog/products-${p}`).join(' '),
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

console.error('\nDjango shard calculation:')
const djangoShards = buildDjangoShards(durations)

const result = {
    matrix: buildMatrix(products, durations),
    run_legacy: runLegacy,
    django_shards: djangoShards,
}
// eslint-disable-next-line no-console
process.stdout.write(JSON.stringify(result) + '\n')
