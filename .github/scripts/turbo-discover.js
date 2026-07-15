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
// DEDICATED_BUCKET_PRODUCTS opt out of grouping and always run alone.
//
// Input:  LEGACY_CHANGED env var ("true"/"false")
//         SCHEMA_CHANGED env var ("true"/"false") — when set and LEGACY_CHANGED
//         is false, schema-impact.js narrows the matrix to products that
//         depend on the affected posthog.schema types.
// Output: JSON on stdout: { matrix, run_legacy, django_shards }
//         Diagnostics on stderr

const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const { analyzeSchemaImpact, readBaseSchema } = require('./schema-impact')

// --- Product shard sizing (same Amdahl shape as Django below) ---
// Each product is atomic for packing, but unlike Django the test pool isn't
// fungible across products — bin-pack products into target-sized shards, and
// multi-shard split any single product that overflows on its own.
// The target is a per-shard test-WORK budget, not a wall-clock promise: the fixed
// per-shard setup (docker stack + temporal boot, deps, collection, ~3-4 min) is paid
// identically by every shard, so it can't skew the split and deliberately stays out
// of the shard-count math — folding it in only inflates counts (see #54280). Walls
// land at target + setup, evenly across shards. JUnit de-taxing in
// optimize_test_durations.py keeps that setup cost out of the timings themselves.
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
// Products that run their OWN temporal suite inside the product test job (backend:test covers
// backend/temporal, and the turbo-tests runner already provisions the temporal profile). For these,
// the temporal durations must count toward product sizing so the product is sharded for that load —
// otherwise a huge suite lands in one unsharded bucket and times out.
const PRODUCTS_RUNNING_TEMPORAL_IN_JOB = new Set(['warehouse-sources'])
// Products that always get their own matrix entry instead of being packed with
// others — isolates a flaky/hang-prone product so it can't cancel bucket-mates
// at the job timeout. Trade-off: a dedicated runner.
const DEDICATED_BUCKET_PRODUCTS = new Set(['batch-exports'])

// --- Staleness detection for .test_durations ---
// When a product's test files on disk significantly outnumber what .test_durations
// covers, the duration data is stale and cost estimates are unreliable. In that
// case, fall back to a file-count-based estimate to prevent under-sharding.
// Threshold: if fewer than 70% of on-disk test files appear in .test_durations,
// treat the product's duration data as stale.
const STALENESS_COVERAGE_THRESHOLD = 0.7
// Conservative per-file fallback duration (seconds) when stale. Accounts for
// parametrized tests that expand a single file into many test cases.
const STALENESS_FALLBACK_SECONDS_PER_FILE = 5

// --- Django shard auto-sizing (Amdahl's law) ---
// wall_clock = overhead + (total_from_durations_file / shards)
//
// .test_durations has migration-tax contamination removed by
// optimize_test_durations.py: tests recorded far above their JUnit call
// time (the DB-setup walk lands on whichever test first hits the DB) are
// floored back to that call time. Durations reflect actual test work.
//
// Per-segment overhead constants below cover the fixed per-shard cost
// outside test work: job setup, pytest collection, per-shard DB setup,
// per-segment infra.
//
// These are calibrated for the PR path, which is >95% of runs. On PRs the
// test DB is primed from a cached pre-migrated schema dump (restore step in
// ci-backend.yml, ~60s) instead of walking Django migrations, so the per-
// shard overhead stays small. Measured as wall_clock minus the shard's
// corrected test work on a PR run with the schema cache hitting:
//   Core:     median ~4.5 min, max ~9 min  → 4 min is tight but holds
//   CorePOE:  median ~4 min                → 4 min
//   Temporal: median ~4 min                → 6 min has headroom for temporal-server boot
//
// Master pushes SKIP the schema-cache restore and walk migrations fresh
// (~7 min), so master shards run ~11 min overhead and blow past the 20 min
// target. That is accepted: master runs are rare, happen uniformly across
// shards, and are where .test_durations is collected anyway. Calibrating up
// to protect them would over-shard every PR. Note the consequence: a PR with
// a schema-cache MISS (stale branch, key drift) falls back to the full walk
// and its shards will also overrun — uniformly, same as master.
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

// --- Test quarantine (.test_quarantine.json) ---
// Schema contract: tools/hogli-commands/hogli_commands/quarantine/core.py.
// This script consumes a deliberately trivial subset of it: pytest entries
// with an explicit `product:<dashed-name>` selector and `mode: "skip"` drop
// the whole product from the matrix (mode "run" entries need no matrix change
// — their tests xfail in-shard). ISO date strings compare lexicographically;
// an entry is active while today <= expires.
const QUARANTINE_FILE = '.test_quarantine.json'

function quarantinedSkipProducts(jsonText, todayISO) {
    const parsed = JSON.parse(jsonText)
    if (parsed?.version !== 1 || !Array.isArray(parsed.entries)) {
        return new Set()
    }
    const products = new Set()
    for (const entry of parsed.entries) {
        if (typeof entry?.id !== 'string' || !entry.id.startsWith('product:')) {continue}
        if ((entry.runner ?? 'pytest') !== 'pytest' || entry.mode !== 'skip') {continue}
        if (typeof entry.expires !== 'string' || entry.expires < todayISO) {continue}
        products.add(entry.id.slice('product:'.length))
    }
    return products
}

function loadQuarantinedSkipProducts(todayISO) {
    try {
        return quarantinedSkipProducts(fs.readFileSync(QUARANTINE_FILE, 'utf-8'), todayISO)
    } catch (e) {
        // Fail-open: a missing or malformed file means no quarantine, never a blocked matrix.
        console.error(`Warning: could not read ${QUARANTINE_FILE} (${e.message}) — quarantine ignored`)
        return new Set()
    }
}

function loadBaseQuarantinedSkipProducts(base, todayISO) {
    // Fail-open: file absent at base (or unreadable ref) means nothing was quarantined there.
    try {
        const raw = readBaseSchema(base, QUARANTINE_FILE)
        return raw === null ? new Set() : quarantinedSkipProducts(raw, todayISO)
    } catch {
        return new Set()
    }
}

// Warn on names matching no real product (catches the dash/underscore mixup:
// the dir is batch_exports but the product is batch-exports), then drop the
// rest from the matrix.
function dropProducts(products, allProducts, names, label) {
    const allProductSet = new Set(allProducts)
    for (const name of names) {
        if (!allProductSet.has(name)) {
            console.error(
                `::warning::${label}: unknown product '${name}' — use the dashed name (e.g. 'batch-exports'), not the directory form`
            )
        }
    }
    const remaining = products.filter((p) => !names.has(p))
    console.error(`${label}: ${[...names].join(',')} — dropped ${products.length - remaining.length} product(s)`)
    return remaining
}

// --- Dependent cascade (tach.toml) ---
// When a product's contract changes, Turbo's graph has no edges to the
// products that depend on it (no workspace deps, no `dependsOn`), so those
// dependents never get retested — see #70556. tach.toml is the graph we
// actually have: `tach check --dependencies` runs in CI, so it can't drift
// from what's importable. Reuse it to compute who transitively depends on a
// changed product's contract.
const TACH_TOML_FILE = 'tach.toml'
const TACH_MODULE_PREFIX = 'products.'

// Turbo package names are dashed; tach module paths and product directories are
// underscored. Every boundary crossing goes through these, so the convention is
// stated once rather than re-derived at each call site.
const productToModule = (product) => product.replace(/-/g, '_')
const moduleToProduct = (module) => module.replace(/_/g, '-')

// Parse tach.toml's [[modules]] blocks into product -> [products it depends
// on]. Keys/values are tach names with the "products." prefix stripped
// (underscores preserved) — callers normalize to/from Turbo's dashed names.
//
// Only products.* modules become nodes or edges. posthog/ee (and the
// common.* utility modules) are dropped on both sides deliberately: they
// aren't products.* so they fall out of the startsWith filter for free. See
// tachDependents for why routing through them would be wrong, not just
// inconvenient.
function parseTachModules(tomlText) {
    const graph = new Map()
    // Each `[[modules]]` block holds exactly one `path` and one `depends_on`
    // before the next block starts — split on the marker and take the first
    // match of each within a block. depends_on entries are plain quoted
    // strings with no nested brackets, so a non-greedy scan to the first `]`
    // is safe even across multi-line lists or lists split across shared lines.
    //
    // Only double-quoted strings are supported. Other valid TOML (single-quoted
    // literals, inline tables) would be dropped by the regexes without error,
    // silently shrinking the cascade — so any entry the regexes can't represent
    // throws instead, which loadTachModuleGraph turns into "test all products".
    // A false trip over-tests; a silent drop under-tests, so err on throwing.
    const blocks = tomlText.split('[[modules]]').slice(1)
    for (const block of blocks) {
        const pathMatch = block.match(/path\s*=\s*"([^"]+)"/)
        if (!pathMatch) {
            if (/^\s*path\s*=/m.test(block)) {
                throw new Error('unsupported `path` syntax in a tach.toml module block (expected a double-quoted string)')
            }
            continue
        }
        const dependsMatch = block.match(/depends_on\s*=\s*\[([\s\S]*?)\]/)
        if (!dependsMatch) {
            if (/^\s*depends_on\s*=/m.test(block)) {
                throw new Error(`unsupported \`depends_on\` syntax for ${pathMatch[1]} in tach.toml (expected a list)`)
            }
            continue
        }
        const leftover = dependsMatch[1].replace(/"[^"]*"/g, '').replace(/#[^\n]*/g, '')
        if (/[^\s,]/.test(leftover)) {
            throw new Error(
                `unsupported \`depends_on\` entry for ${pathMatch[1]} in tach.toml (expected double-quoted strings): ${leftover.trim().slice(0, 80)}`
            )
        }
        const modulePath = pathMatch[1]
        if (!modulePath.startsWith(TACH_MODULE_PREFIX)) {continue}
        const product = modulePath.slice(TACH_MODULE_PREFIX.length)
        const deps = [...dependsMatch[1].matchAll(/"([^"]+)"/g)]
            .map((m) => m[1])
            .filter((d) => d.startsWith(TACH_MODULE_PREFIX))
            .map((d) => d.slice(TACH_MODULE_PREFIX.length))
        graph.set(product, deps)
    }
    return graph
}

// Reverse transitive closure over the product graph: who (transitively)
// depends on any of `changedProducts`? Input/output are Turbo-style names
// (dashes); moduleGraph keys/values are tach-style (underscores) — convert
// at the boundary in both directions, since a mismatch here doesn't error,
// it just silently returns nothing (a false negative — exactly the bug this
// is fixing).
//
// Deliberately never traverses through posthog/ee (moduleGraph has already
// dropped them as nodes): routing through core degenerates the cascade to
// "every product" — most products depend on core and core depends on most
// products, so any path through it reaches the whole graph. Core's own tests
// aren't at risk either way — a contract change already forces runLegacy so
// the full Django suite runs. The accepted gap is the mediated path (product
// A -> a core wrapper -> product X's facade); measurement showed it's mostly
// either unreachable (no product imports the file) or funnels through a few
// composition-root hubs where "imports Team" doesn't mean "depends on a
// product's behavior" — the residual after excluding those is a handful of
// narrow wrappers reaching at most a few products each.
function tachDependents(changedProducts, moduleGraph) {
    const reverse = new Map()
    for (const [product, deps] of moduleGraph) {
        for (const dep of deps) {
            if (!reverse.has(dep)) {reverse.set(dep, [])}
            reverse.get(dep).push(product)
        }
    }

    const changedSet = new Set(changedProducts.map(productToModule))
    const visited = new Set()
    const queue = [...changedSet]
    while (queue.length > 0) {
        const current = queue.shift()
        for (const dependent of reverse.get(current) || []) {
            if (visited.has(dependent) || changedSet.has(dependent)) {continue}
            visited.add(dependent)
            queue.push(dependent)
        }
    }
    return [...visited].map(moduleToProduct)
}

// Returns null when the graph can't be read or parsed. Callers must treat null as
// "unknown dependents" and widen the matrix — never as "no dependents", which would
// silently under-test exactly the contract changes this cascade guards.
function loadTachModuleGraph() {
    let text
    try {
        text = fs.readFileSync(TACH_TOML_FILE, 'utf-8')
    } catch (e) {
        console.error(`::warning::Could not read ${TACH_TOML_FILE} (${e.message}) — falling back to testing all products`)
        return null
    }
    try {
        return parseTachModules(text)
    } catch (e) {
        console.error(`::warning::Could not parse ${TACH_TOML_FILE} (${e.message}) — falling back to testing all products`)
        return null
    }
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

// Recursively collect test files (test_*.py / *_test.py) under a directory.
function collectTestFiles(dir) {
    const files = []
    let entries
    try {
        entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
        return files
    }
    for (const entry of entries) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            files.push(...collectTestFiles(full))
        } else if (
            entry.isFile() &&
            entry.name.endsWith('.py') &&
            (entry.name.startsWith('test_') || entry.name.endsWith('_test.py'))
        ) {
            files.push(full)
        }
    }
    return files
}

function productPrefix(product) {
    return `products/${productToModule(product)}/`
}

// Check if .test_durations is stale for a product by comparing on-disk test
// file coverage vs recorded entries. Returns { stale, fileCount, coveredCount, coverage }.
function checkProductStaleness(product, durations) {
    if (!durations) {return { stale: true, fileCount: 0, coveredCount: 0, coverage: 0 }}
    const dirName = productToModule(product)
    const productDir = path.join('products', dirName)
    const testFiles = collectTestFiles(productDir)
    if (testFiles.length === 0) {return { stale: false, fileCount: 0, coveredCount: 0, coverage: 0 }}

    const prefix = productPrefix(product)
    // Build set of file paths that have at least one entry in durations
    const coveredFiles = new Set()
    for (const testPath of Object.keys(durations)) {
        if (testPath.startsWith(prefix)) {
            // Extract file path (everything before ::)
            const filePart = testPath.split('::')[0]
            coveredFiles.add(filePart)
        }
    }

    let coveredCount = 0
    for (const file of testFiles) {
        if (coveredFiles.has(file)) {coveredCount++}
    }

    const coverage = coveredCount / testFiles.length
    return { stale: coverage < STALENESS_COVERAGE_THRESHOLD, fileCount: testFiles.length, coveredCount, coverage }
}

function getProductDuration(product, durations) {
    if (!durations) {
        return 0
    }
    const prefix = productPrefix(product)
    // Temporal tests are normally excluded (they run in the Django Temporal segment), but a product
    // that runs its own temporal suite in the product job must count them toward its size.
    const excluded = PRODUCTS_RUNNING_TEMPORAL_IN_JOB.has(product) ? [] : EXCLUDED_PATH_SEGMENTS
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (test.startsWith(prefix) && !excluded.some((seg) => test.includes(seg))) {
            total += dur
        }
    }
    return total
}

function productEffectiveCost(product, durations) {
    let base = getProductDuration(product, durations)
    const staleness = checkProductStaleness(product, durations)
    if (staleness.stale && staleness.fileCount > 0) {
        base = Math.max(base, staleness.fileCount * STALENESS_FALLBACK_SECONDS_PER_FILE)
    }
    return base * PRODUCT_SAFETY_FACTOR + PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS
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
    if (!durations) {return 0}
    const { include, exclude } = DJANGO_SEGMENTS[segment]
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (!include.some((p) => test.startsWith(p))) {continue}
        if (exclude.some((p) => test.startsWith(p))) {continue}
        total += dur
    }
    return total
}

// Fallback shard counts used when .test_durations is missing.
const DJANGO_FALLBACK_SHARDS = { Core: 38, CorePOE: 7, Temporal: 7 }

function calculateShards(totalWorkSeconds, overheadSeconds) {
    const testBudget = DJANGO_TARGET_WALL_SECONDS - overheadSeconds
    if (testBudget <= 0) {return DJANGO_MAX_SHARDS}
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
        const staleness = checkProductStaleness(product, durations)
        let raw = getProductDuration(product, durations) + PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS

        // Staleness guard: if .test_durations has poor coverage for this product,
        // use a file-count-based fallback to avoid under-sharding.
        if (staleness.stale && staleness.fileCount > 0) {
            const fallbackRaw = staleness.fileCount * STALENESS_FALLBACK_SECONDS_PER_FILE + PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS
            if (fallbackRaw > raw) {
                console.error(
                    `  ${product}: .test_durations stale — ${staleness.coveredCount}/${staleness.fileCount} test files covered ` +
                    `(${(staleness.coverage * 100).toFixed(0)}%). Using fallback estimate: ${(fallbackRaw / 60).toFixed(1)} min (was ${(raw / 60).toFixed(1)} min)`
                )
                console.error(
                    `::warning title=Stale .test_durations::Product '${product}' has only ${staleness.coveredCount}/${staleness.fileCount} ` +
                    `test files covered in .test_durations. Duration estimates are unreliable — using fallback sharding.`
                )
                raw = fallbackRaw
            }
        }

        if (raw > PRODUCT_TARGET_WALL_SECONDS) {
            const shards = Math.ceil(raw / PRODUCT_TARGET_WALL_SECONDS)
            console.error(`  ${product}: ${(raw / 60).toFixed(1)} min raw → split across ${shards} shards`)
            const filters = `--filter=@posthog/products-${product}`
            // optimal_chunks (PostHog pytest-split fork) makes the same contiguous,
            // order-preserving cuts as duration_based_chunks but balances them
            // optimally. The greedy rule in duration_based_chunks lets every shard
            // overrun the per-shard average, which on skewed suites starves trailing
            // shards down to zero tests (pytest exit 5, "no tests collected").
            for (let i = 1; i <= shards; i++) {
                matrix.push({
                    group: `${product} (${i}/${shards})`,
                    filters,
                    pytest_args: `-- --splits ${shards} --group ${i} --splitting-algorithm optimal_chunks`,
                })
            }
        } else if (DEDICATED_BUCKET_PRODUCTS.has(product)) {
            console.error(`  ${product}: ${(raw / 60).toFixed(1)} min raw → dedicated bucket (never packed)`)
            matrix.push({
                group: product,
                filters: `--filter=@posthog/products-${product}`,
                pytest_args: '',
            })
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

// Exported for unit tests only — not part of the public API.
module.exports = {
    collectTestFiles,
    checkProductStaleness,
    productPrefix,
    productEffectiveCost,
    STALENESS_COVERAGE_THRESHOLD,
    STALENESS_FALLBACK_SECONDS_PER_FILE,
    parseTachModules,
    tachDependents,
}

// --- Main ---
if (require.main === module) {

const legacyChanged = process.env.LEGACY_CHANGED === 'true'
const schemaChanged = process.env.SCHEMA_CHANGED === 'true'

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
const allProductSet = new Set(allProducts)

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
            const tachGraph = loadTachModuleGraph()
            if (tachGraph === null) {
                // Fail toward over-testing, like the quarantine loaders above: without the
                // graph we cannot know which products depend on the changed contract, and
                // guessing "none" silently recreates the gap this cascade exists to close.
                console.error('Dependent cascade unavailable — testing all products rather than risk skipping a dependent')
                products = allProducts
            } else {
                const dependents = tachDependents(affectedContracts, tachGraph).filter((p) => allProductSet.has(p))
                if (dependents.length > 0) {
                    console.error(
                        `Dependent products cascaded in via tach.toml: ${JSON.stringify(dependents)} (transitively depend on ${JSON.stringify(affectedContracts)})`
                    )
                }
                products = [...new Set([...affectedProducts, ...dependents])].sort()
            }
        } else {
            console.error('Only isolated product internals changed — Django can be skipped')
            runLegacy = false
            products = affectedProducts
        }
    } else {
        console.error('No product changes detected')
        products = []
        runLegacy = false
    }

    if (schemaChanged) {
        const impact = analyzeSchemaImpact({ scmBase: process.env.TURBO_SCM_BASE })
        console.error(`Schema impact: ${JSON.stringify({ kind: impact.kind, counts: impact.counts, reason: impact.reason })}`)
        if (impact.kind === 'fallback') {
            console.error(`Schema diff unavailable (${impact.reason}) — falling back to all products + Django`)
            products = allProducts
            runLegacy = true
        } else {
            if (impact.kind === 'impacting') {
                console.error(`Schema-affected products: ${JSON.stringify(impact.affectedProducts)}`)
                if (impact.wildcardProducts && impact.wildcardProducts.length > 0) {
                    console.error(
                        `Products with unresolved schema module imports (always tested): ${JSON.stringify(impact.wildcardProducts)}`
                    )
                }
                products = [...new Set([...products, ...impact.affectedProducts])].sort()
            } else {
                console.error('Schema change is purely additive — no extra products needed')
            }
            // Core (posthog/, ee/, etc.) imports schema heavily; always run Django on schema changes.
            runLegacy = true
        }
    }
}

// Kill switch: products named in the SKIP_PRODUCT_TESTS repo variable (comma-
// separated) are dropped from the matrix without a code change — use it to stop
// running, and blocking on, a product whose tests are temporarily too flaky.
const skipProducts = new Set((process.env.SKIP_PRODUCT_TESTS || '').split(',').map((p) => p.trim()).filter(Boolean))
if (skipProducts.size > 0) {
    products = dropProducts(products, allProducts, skipProducts, 'SKIP_PRODUCT_TESTS')
}

const todayISO = new Date().toISOString().slice(0, 10)
const quarantinedProducts = loadQuarantinedSkipProducts(todayISO)
if (quarantinedProducts.size > 0) {
    products = dropProducts(products, allProducts, quarantinedProducts, 'Quarantined products (mode: skip)')
}

// Un-quarantining must re-run the suite. Today the ci-backend `legacy` paths-
// filter already forces a full run on any PR touching the quarantine file, so
// this diff against the merge base rarely changes the outcome — it is the
// backstop that keeps product re-runs correct if that coarse trigger is ever
// narrowed (Turbo itself never sees .test_quarantine.json as a product input).
if (process.env.TURBO_SCM_BASE) {
    const baseQuarantined = loadBaseQuarantinedSkipProducts(process.env.TURBO_SCM_BASE, todayISO)
    const allProductSet = new Set(allProducts)
    const productSet = new Set(products)
    for (const name of baseQuarantined) {
        if (quarantinedProducts.has(name) || skipProducts.has(name)) {continue}
        if (!allProductSet.has(name) || productSet.has(name)) {continue}
        console.error(`Quarantine lifted for '${name}' since ${process.env.TURBO_SCM_BASE} — forced into matrix`)
        products.push(name)
    }
    products.sort()
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

} // end if (require.main === module)
