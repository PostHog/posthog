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
// Backend test selection: the selector's output (SELECTION_JSON) decides which
// Django tests run and, on a legacy diff, which products stay in the matrix. One
// verdict feeds both, so the two matrices can never disagree about whether the
// selection is trustworthy.
//
// Input:  LEGACY_CHANGED env var ("true"/"false")
//         SCHEMA_CHANGED env var ("true"/"false") — when set and LEGACY_CHANGED
//         is false, schema-impact.js narrows the matrix to products that
//         depend on the affected posthog.schema types.
//         SELECTION_JSON — path to the backend test selector's output, empty when
//         it did not run or failed.
//         SELECTION_APPLIES ("true"/"false") — whether this run is one that selects
//         at all; false leaves the Django matrix alone.
//         SELECTION_DISABLED ("true"/"false") — the DISABLE_BACKEND_TEST_SELECTION
//         kill switch.
//         PR_DRAFT ("true"/"false") — what an untrusted selection falls back to.
// Output: JSON on stdout: { matrix, run_legacy, django_shards, selection }
//         Diagnostics on stderr

const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')
const { analyzeSchemaImpact, readBaseSchema } = require('./schema-impact')
const { loadContractSurfaces } = require('./trunk-impacted-targets')

// --- Product shard sizing (same Amdahl shape as Django below) ---
// The test pool is not fungible across products, so a product is the unit of
// work: bin-pack products into target-sized jobs, and multi-shard split any
// single product that overflows on its own. A job runs what it holds
// sequentially, so its wall is the sum of its parts, not the max.
// One flat wall-clock target for every test shard, Django and products alike.
// Predictability is the point: a dev who kicks off CI knows what a shard costs
// without knowing which segment it is. Sizing solves wall = overhead + work/n
// for n, so the target is a promise about the PR lane (where the overheads below
// are fitted); master pays extra overhead (full migration replay) on top.
// A full run's wall is the pre-shard preamble plus the slowest of its shards.
// The preamble (discovery, matrix build, runner start) measures ~5.5 min, and
// sizing bounds the slowest shard at the target rather than the average, so a
// 12-minute shard target puts a full PR run near 18 minutes end to end.
const TARGET_WALL_SECONDS = 12 * 60
// Per-product cost within a runner: turbo dispatch, pytest collection, Django
// init. First product pays ~45s, subsequent ~15s; use 60s as a conservative
// average that also absorbs the amortized portion of runner startup.
const PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS = 60
// Headroom on a packed bucket, covering error in the recorded durations alone.
// A bucket runs its products sequentially, so its wall is the sum of its parts
// and it needs no allowance for an uneven split. That allowance belongs to the
// split path, which derives its own in productSplitShards.
const PRODUCT_BUCKET_SAFETY_FACTOR = 1.1
// No headroom constant for a split product: the gap between the mean shard that
// sizing solves for and the max shard that sets the wall is derived per product
// in productSplitShards below.
// Fitted per-shard overhead for a split product job. Two measured parts, from
// run 32717208712: the job base (docker stack, deps, turbo dispatch) is
// mean(job wall - JUnit suite time), 247-413s across 12 bucket jobs (median
// 282s, 263s over the 17 warehouse-sources shards); the session cost
// (collection, session fixtures) is re-paid in full by every shard of a split
// and grows with suite size (128s/shard on warehouse-sources, ~15s on small
// products). Only large products split, so the constant carries a large
// product's session: ~270 base + ~130 session.
const PRODUCT_JOB_OVERHEAD_SECONDS = 400
// The base alone, for packed buckets: their products are small, so the session
// share is the per-product overhead below rather than a large suite's collection.
const PRODUCT_JOB_BASE_OVERHEAD_SECONDS = 270
// Sentinel entry the timing workflow writes into .test_durations after it scales
// the product entries to their JUnit-measured totals (see
// optimize_test_durations.py). Product jobs record call-only durations, which
// under-report fixture-heavy suites several-fold (warehouse-sources: 16 min
// recorded vs 38 min real), so unscaled sums must not be trusted as magnitudes.
// The key is not a real file, so pruning drops it: read it before pruning. It
// survives the --store-durations round trip like any restored entry.
const PRODUCTS_SCALED_MARKER = 'products/.junit-scaled'
// Temporal tests of products NOT listed below run in Django CI's Temporal segment,
// so they must not also count toward that product's own size.
const EXCLUDED_PATH_SEGMENTS = ['/temporal/']
// Products that run their OWN temporal suite inside the product test job, so their
// temporal durations count toward product sizing, otherwise a big suite lands in
// one unsharded bucket and times out.
//
// Every shard in backend CI already starts COMPOSE_PROFILES=temporal, in the django
// job and in turbo-tests alike, so running a temporal suite here costs no extra
// infrastructure. The product's backend:test must name its temporal path.
const PRODUCTS_RUNNING_TEMPORAL_IN_JOB = new Set([
    'batch-exports',
    'managed-warehouse',
    'tasks',
    'warehouse-sources',
])
// Products that always get their own matrix entry instead of sharing one, so a
// hang cannot cancel job-mates when the job timeout fires. The cost is a
// dedicated runner, so a product belongs here only while its wall runs close
// enough to the job timeout that a hang is a realistic outcome.
const DEDICATED_BUCKET_PRODUCTS = new Set()

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
// time (the DB-setup walk lands on the first DB-touching test whenever a
// run built the DB in-pytest) are floored back to that call time.
// Durations reflect actual test work.
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
// (~7 min), so master shards carry a much larger overhead. Sizing at a fixed
// efficiency handles that on its own: a bigger O means fewer shards, each
// doing more work, which is the correct response. A fixed wall target could
// not express it, because the same number meant two different things per lane.
//
// Refitted from run 32713377568 as mean(shard wall) - work/shards. The mean is
// exact whatever the split quality was, because the shards partition the work.
//   Core     6 shards, mean 16.32 min, work 68.3 min -> 4.93
//   CorePOE  3 shards, mean  6.67 min, work  6.0 min -> 4.67
//   Temporal 6 shards, mean 12.17 min, work 54.8 min -> 3.03
// Temporal was previously the highest of the three and is in fact the lowest,
// which is what left it under-sharded relative to Core.
const DJANGO_OVERHEAD_SECONDS_BY_SEGMENT = {
    Core: 295,
    CorePOE: 280,
    Temporal: 182,
}
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

// A product that ships the contract-check script but no turbo.json of its own
// inherits the root task, whose inputs are the product's whole backend. Every
// backend edit then reads as a contract change, so the isolation it claims can
// never pay out. Requiring the narrowed declaration keeps "isolated" meaning
// what turbo-discover uses it for, and reading it through loadContractSurfaces
// keeps this reader and the Trunk lane reader on one definition.
function getIsolatedProducts(contractTasks, repoRoot = process.cwd()) {
    const products = contractTasks.map((t) => packageToProduct(t.package))
    // Package names use dashes, product directories use underscores; the surface
    // reader resolves products/<dir>/turbo.json, so look up the directory form.
    const toDir = (product) => product.replace(/-/g, '_')
    const surfaces = loadContractSurfaces(repoRoot, products.map(toDir))
    return new Set(products.filter((product) => surfaces.has(toDir(product))))
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

// Turbo's affected query for one task, null when it fails. The caller decides whether
// that is fatal (a products-only diff has nothing else to go on) or only disables the
// narrowed product matrix on a legacy diff.
function queryAffectedTasks(taskName) {
    try {
        return parseAffectedTasks(runTurbo(affectedArgs(taskName)))
    } catch (e) {
        console.error(`::warning::turbo affected query for ${taskName} failed: ${e.message}`)
        if (e.stderr) {
            console.error(e.stderr.toString().slice(0, 1000))
        }
        return null
    }
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

// --- Dependent cascade (tach map) ---
// When a product's contract changes, Turbo's graph has no edges to the
// products that depend on it (no workspace deps, no `dependsOn`), so those
// dependents never get retested — see #70556. `tach map` is the graph we
// actually have: it walks the real imports of every Python file under
// tach.toml's source roots, the same imports `tach check --dependencies`
// enforces in CI, so it can't drift from what's importable. It reads the files
// rather than the declared depends_on lists, so an import the declaration
// misses (a module path in a string, a test that imports another product's
// facade) still cascades. Reuse it to compute who transitively depends on a
// changed product's contract.
//
// tach_map.py pins tach in its PEP 723 block and runs under `uv run
// --no-project`, so the callers need uv and nothing from the Python project.
const TACH_MAP_SCRIPT = path.join(__dirname, 'tach_map.py')
const PRODUCTS_DIR = 'products/'

// Turbo package names are dashed; product directories are underscored. Every
// boundary crossing goes through these, so the convention is stated once
// rather than re-derived at each call site.
const productToModule = (product) => product.replace(/-/g, '_')
const moduleToProduct = (module) => module.replace(/_/g, '-')

// The product that owns a file path from the map, or null for a file outside
// products/ (posthog, ee, common, tools) and for the loose files directly under
// products/ (conftest.py, __init__.py).
function productOfFile(file) {
    if (!file.startsWith(PRODUCTS_DIR)) {
        return null
    }
    const [product, rest] = file.slice(PRODUCTS_DIR.length).split('/', 2)
    return rest === undefined ? null : product
}

// Collapse tach's file map ({ file: [files that import it] }) into
// product -> [products it imports]. Keys and values are product directory
// names (underscores); callers normalize to/from Turbo's dashed names. Every
// product that owns a file in the map is a key, with or without cross-product
// imports, so a reader can tell "no importers" from "not walked".
//
// Files outside products/ (posthog, ee, common) are dropped on both sides
// deliberately. See tachDependents for why routing through them would be
// wrong, not just inconvenient. Test files stay in: a test that imports
// another product's facade depends on that product as much as production
// code does.
function productGraphFromTachMap(fileMap) {
    const graph = new Map()
    const node = (product) => {
        if (!graph.has(product)) {
            graph.set(product, new Set())
        }
        return graph.get(product)
    }
    for (const [imported, importers] of Object.entries(fileMap)) {
        const importedProduct = productOfFile(imported)
        if (importedProduct !== null) {
            node(importedProduct)
        }
        for (const importer of importers) {
            const importerProduct = productOfFile(importer)
            if (importerProduct === null) {
                continue
            }
            const deps = node(importerProduct)
            if (importedProduct !== null && importedProduct !== importerProduct) {
                deps.add(importedProduct)
            }
        }
    }
    return new Map([...graph].map(([product, deps]) => [product, [...deps].sort()]))
}

// Reverse transitive closure over the product graph: who (transitively)
// depends on any of `changedProducts`? Input/output are Turbo-style names
// (dashes); moduleGraph keys/values are directory names (underscores) — convert
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
//
// `direct` stops the walk after the first hop. Test selection must stay
// transitive, because a change in A can break C's tests through B without C
// ever importing A. Merge-queue lane assignment asks a narrower question and
// passes direct: true; see trunk-impacted-targets.js for why one hop is the
// boundary there.
function tachDependents(changedProducts, moduleGraph, { direct = false } = {}) {
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
            if (!direct) {queue.push(dependent)}
        }
    }
    return [...visited].map(moduleToProduct)
}

// Runs tach_map.py in repoRoot and returns the product graph, or null when uv
// is missing, the run fails, or it prints something that is not the map. Callers
// must treat null as "unknown dependents" and widen the matrix — never as "no
// dependents", which would silently under-test exactly the contract changes
// this cascade guards.
//
// tach map exits 0 and drops a file it cannot parse, so a syntax error hides
// that file's imports. That cannot under-test here: a file broken on master
// fails ruff and every import of it, and a file the PR broke sits in a product
// Turbo already selects.
//
// The run walks every Python file and takes seconds, so the result is kept per
// process; a second caller gets the same graph, a failure included.
const tachModuleGraphByRoot = new Map()

function loadTachModuleGraph(repoRoot = process.cwd()) {
    if (!tachModuleGraphByRoot.has(repoRoot)) {
        tachModuleGraphByRoot.set(repoRoot, runTachMap(repoRoot))
    }
    return tachModuleGraphByRoot.get(repoRoot)
}

function runTachMap(repoRoot) {
    let raw
    try {
        raw = execFileSync('uv', ['run', '--no-project', TACH_MAP_SCRIPT], { ...TURBO_EXEC_OPTS, cwd: repoRoot })
    } catch (e) {
        console.error(`::warning::tach map failed (${e.message}) — the dependent cascade widens to every product`)
        return null
    }
    try {
        return productGraphFromTachMap(JSON.parse(raw))
    } catch (e) {
        console.error(`::warning::Could not parse the tach map (${e.message}) — the dependent cascade widens to every product`)
        return null
    }
}

// Python files under products/ that the diff deleted, or null when the diff
// cannot be read. Renames count as deletions of the old path. Empty without a
// base ref: a push run tests everything regardless.
//
// The map is read from the head tree, so a deleted file is not a key in it and
// an importer of that file has no edge left; the importer's suite would be the
// one that fails on the missing module. Any such file makes the cascade
// unknown, so callers widen on it as they do on an unreadable map.
function deletedProductPythonFiles() {
    const base = process.env.TURBO_SCM_BASE
    if (!base) {
        return []
    }
    try {
        return execFileSync(
            'git',
            ['diff', '--name-only', '--no-renames', '--diff-filter=D', `${base}...HEAD`, '--', 'products/'],
            TURBO_EXEC_OPTS
        )
            .split('\n')
            .filter((file) => file.endsWith('.py') && productOfFile(file) !== null)
    } catch (e) {
        console.error(`::warning::Could not list deleted files against ${base} (${e.message}) — the dependent cascade widens to every product`)
        return null
    }
}

// Products that transitively depend on `products` per the tach map, or null when
// the map cannot be read. Callers treat null as "unknown dependents" and widen.
function tachDependentProducts(products, allProductSet) {
    const deleted = deletedProductPythonFiles()
    if (deleted === null) {
        return null
    }
    if (deleted.length > 0) {
        console.error(`Deleted product files have no importer edges in the tach map: ${JSON.stringify(deleted)} — the dependent cascade widens to every product`)
        return null
    }
    const tachGraph = loadTachModuleGraph()
    if (tachGraph === null) {
        return null
    }
    return tachDependents(products, tachGraph).filter((p) => allProductSet.has(p))
}

// Products a schema change reaches, [] for a purely additive change, or null when
// the schema diff is unavailable and every product has to run.
function schemaAffectedProducts() {
    const impact = analyzeSchemaImpact({ scmBase: process.env.TURBO_SCM_BASE })
    console.error(`Schema impact: ${JSON.stringify({ kind: impact.kind, counts: impact.counts, reason: impact.reason })}`)
    if (impact.kind === 'fallback') {
        return null
    }
    if (impact.kind !== 'impacting') {
        console.error('Schema change is purely additive — no extra products needed')
        return []
    }
    console.error(`Schema-affected products: ${JSON.stringify(impact.affectedProducts)}`)
    if (impact.wildcardProducts && impact.wildcardProducts.length > 0) {
        console.error(
            `Products with unresolved schema module imports (always tested): ${JSON.stringify(impact.wildcardProducts)}`
        )
    }
    return impact.affectedProducts
}

// The products a legacy diff must test whatever the backend test selector reached: the
// ones Turbo saw change, their tach dependents, and the ones a schema change reaches.
// Null when any of that is unknowable, which callers must treat as "do not narrow".
function legacyMustRunProducts(affectedTasks, allProductSet, schemaChanged) {
    const affected = getAffectedTaskProducts(affectedTasks)
    const dependents = tachDependentProducts(affected, allProductSet)
    if (dependents === null) {
        return null
    }
    const schemaProducts = schemaChanged ? schemaAffectedProducts() : []
    if (schemaProducts === null) {
        return null
    }
    return [...new Set([...affected, ...dependents, ...schemaProducts])]
}

// The backend test selector's output (tools/snob_backend_test_selection_shadow.py), or
// null when it is absent or unreadable.
function loadSelection(path) {
    if (!path) {
        return null
    }
    try {
        return JSON.parse(fs.readFileSync(path, 'utf-8'))
    } catch (e) {
        console.error(`::warning::Could not read the backend test selection at ${path} (${e.message}) — the full matrices will run`)
        return null
    }
}

// Products to test on a legacy diff once the selection is trusted: the must-run set
// plus the products the selector reached through the import graph. Callers narrow only
// on a `selected` verdict, so the trust rules live in decideSelection, not here.
function narrowedProducts(products, mustRunProducts, selection) {
    const selected = ((selection.combined && selection.combined.products) || []).map(moduleToProduct)
    const keep = new Set([...mustRunProducts, ...selected])
    console.error(`Products reached by the backend test selector: ${JSON.stringify(selected)}`)
    return products.filter((p) => keep.has(p))
}

// Strips non-finite values so a single corrupted entry can't NaN-poison the
// matrix (Math.ceil(NaN) silently propagates through sort/compare, making a
// product vanish from packing without an error). Returns null when the file is
// absent or is not a JSON object.

function loadDurationsFile(file) {
    let parsed
    try {
        parsed = JSON.parse(fs.readFileSync(file, 'utf-8'))
    } catch {
        return null
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        console.error(`Warning: ${file} is not a JSON object, ignoring it`)
        return null
    }
    let dropped = 0
    for (const [k, v] of Object.entries(parsed)) {
        if (typeof v !== 'number' || !Number.isFinite(v)) {
            delete parsed[k]
            dropped++
        }
    }
    if (dropped > 0) {
        console.error(`Warning: dropped ${dropped} non-numeric entries from ${file}`)
    }
    return parsed
}

function loadTestDurations() {
    const parsed = loadDurationsFile('.test_durations')
    if (!parsed) {
        console.error('Warning: .test_durations not usable, sharding disabled')
    }
    return parsed
}

// The per-segment plan files are scoped to the node ids one run's JUnit
// actually recorded. Used here only as an allowlist: DJANGO_SEGMENTS stays the
// definition of what a segment runs, and JUnit removes what did not run.
const SEGMENT_PLAN_FILES = { Core: '.test_durations.core', Temporal: '.test_durations.temporal' }

function loadRanNodeIds() {
    const ran = {}
    for (const [segment, file] of Object.entries(SEGMENT_PLAN_FILES)) {
        // Cache-only files. Absent on a miss, and the pruned union covers that.
        const parsed = loadDurationsFile(file)
        if (parsed) {
            ran[segment] = new Set(Object.keys(parsed))
        }
    }
    return ran
}

const fileExistsCache = new Map()

function nodeIdFileExists(nodeId) {
    const file = nodeId.split('::')[0]
    let exists = fileExistsCache.get(file)
    if (exists === undefined) {
        exists = fs.existsSync(file)
        fileExistsCache.set(file, exists)
    }
    return exists
}

// Splitting is immune to dead entries, because pytest-split drops unknown node ids
// before it weights anything. Sizing is not: every total here is a raw sum
// over the union, so dead seconds inflate the shard count with no symptom
// other than fast green shards.
function pruneDeadDurations(durations) {
    if (!durations) {return durations}
    const live = {}
    let deadIds = 0
    let deadSeconds = 0
    for (const [nodeId, dur] of Object.entries(durations)) {
        if (nodeIdFileExists(nodeId)) {
            live[nodeId] = dur
        } else {
            deadIds++
            deadSeconds += dur
        }
    }
    if (deadIds > 0) {
        console.error(
            `  .test_durations: dropped ${deadIds} entries (${(deadSeconds / 60).toFixed(1)} min) for files no longer on disk`
        )
    }
    return live
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

// The longest single test in a product. pytest-split cuts between tests, never
// inside one, so this is the irreducible grain of any split and it bounds how
// far the worst chunk can run past the mean.
// Budget of test work one product shard can hold, mirroring calculateShards.
function productShardBudget() {
    return Math.max(TARGET_WALL_SECONDS - PRODUCT_JOB_OVERHEAD_SECONDS, PRODUCT_JOB_OVERHEAD_SECONDS / 2, 1)
}

// The parts of a product's duration distribution that sizing needs. Two tests
// longer than half a shard's budget can never share a shard, so those are counted
// rather than summed; the rest are summed, with their own longest, because a
// contiguous chunk of them runs at most one of them past the mean.
function getProductShape(product, durations) {
    const shape = { work: 0, maxTest: 0, heavyCount: 0, lightWork: 0, maxLight: 0, testCount: 0 }
    if (!durations) {
        return shape
    }
    const prefix = productPrefix(product)
    const excluded = PRODUCTS_RUNNING_TEMPORAL_IN_JOB.has(product) ? [] : EXCLUDED_PATH_SEGMENTS
    const heavyThreshold = productShardBudget() / 2
    for (const [test, dur] of Object.entries(durations)) {
        if (!test.startsWith(prefix) || excluded.some((seg) => test.includes(seg))) {
            continue
        }
        shape.work += dur
        shape.testCount += 1
        shape.maxTest = Math.max(shape.maxTest, dur)
        if (dur > heavyThreshold) {
            shape.heavyCount += 1
        } else {
            shape.lightWork += dur
            shape.maxLight = Math.max(shape.maxLight, dur)
        }
    }
    return shape
}

// One definition of a product's work estimate, shared by the split decision
// (buildMatrix) and the bucket cost (packProducts), so they cannot disagree.
//
// When the union carries the scaled marker, its product sums equal the
// JUnit-measured totals and are trusted as magnitudes; the file-count guess then
// only covers products with no entries at all (a brand-new product). Without the
// marker the sums are call-only undercounts, so the legacy staleness guard
// applies: with poor coverage, guess work from file counts to avoid
// under-sharding. `staleUnionWork` is non-null exactly when the guess replaced
// the recorded sum, so the caller can log it once.
function resolveProductSizing(product, durations, productsScaled = false) {
    const shape = getProductShape(product, durations)
    if (productsScaled && shape.work > 0) {
        return { ...shape, staleUnionWork: null, staleness: null }
    }
    const staleness = checkProductStaleness(product, durations)
    if (staleness.stale && staleness.fileCount > 0) {
        const fallbackWork = staleness.fileCount * STALENESS_FALLBACK_SECONDS_PER_FILE
        if (fallbackWork > shape.work) {
            // The tests the map does record are still measurements, and a heavy one
            // holds a shard whatever the coverage. Keep those and treat only the
            // guessed remainder as light, at one file's worth per test.
            const recordedHeavyWork = shape.work - shape.lightWork
            return {
                work: fallbackWork,
                maxTest: Math.max(shape.maxTest, STALENESS_FALLBACK_SECONDS_PER_FILE),
                heavyCount: shape.heavyCount,
                lightWork: Math.max(fallbackWork - recordedHeavyWork, 0),
                maxLight: Math.max(shape.maxLight, STALENESS_FALLBACK_SECONDS_PER_FILE),
                testCount: Math.max(shape.testCount, staleness.fileCount),
                staleUnionWork: shape.work,
                staleness,
            }
        }
    }
    return { ...shape, staleUnionWork: null, staleness: null }
}

function productEffectiveCost(product, durations, productsScaled = false) {
    const { work } = resolveProductSizing(product, durations, productsScaled)
    return work * PRODUCT_BUCKET_SAFETY_FACTOR + PRODUCT_PER_PRODUCT_OVERHEAD_SECONDS
}

// First-fit-decreasing bin packing into TARGET-sized jobs. Sorts products by
// effective cost descending so the largest products land first and small ones
// fill the gaps. Each job caps at the wall target minus the base overhead it
// pays once, so the effective costs only compete for the remaining budget.
// `seedJobs` are jobs that already hold work — a split product's last shard —
// and they sit first so their leftover budget is used before a new runner is
// started. A seed carries its own base overhead, which is a large product's
// session cost rather than the packed-bucket base.
function packProducts(products, durations, productsScaled = false, seedJobs = []) {
    const items = products
        .map((product) => ({ product, cost: productEffectiveCost(product, durations, productsScaled) }))
        .sort((a, b) => b.cost - a.cost)

    const buckets = [...seedJobs]
    for (const { product, cost } of items) {
        let placed = false
        for (const bucket of buckets) {
            if (bucket.cost + cost <= TARGET_WALL_SECONDS - bucket.baseOverhead) {
                bucket.products.push(product)
                bucket.cost += cost
                placed = true
                break
            }
        }
        if (!placed) {
            buckets.push({
                label: null,
                legs: [],
                products: [product],
                cost,
                baseOverhead: PRODUCT_JOB_BASE_OVERHEAD_SECONDS,
            })
        }
    }
    return buckets
}

// Path filters matching the Django workflow pytest invocations. A segment that
// drifts from its pytest targets sizes shards for a run that never happens, so
// turbo-discover.test.js asserts these against ci-backend.yml itself.
// Core: posthog/ + ee/ minus the paths the Core invocation --ignore's
// CorePOE: the POE-off safeguard allowlist, a subset of Core's pool run under the legacy joined mode
// Temporal: posthog/temporal + the product temporal/emission suites it runs alongside
const DJANGO_SEGMENTS = {
    Core: {
        include: ['posthog/', 'ee/'],
        exclude: ['posthog/temporal/', 'posthog/dags/', 'common/hogvm/python/test/', 'posthog/test/repo_invariants/'],
    },
    CorePOE: {
        // Keep in sync with the person-on-events pytest targets in
        // ci-backend.yml's "Run Core tests" step.
        include: [
            'posthog/clickhouse/',
            'posthog/queries/',
            'posthog/api/test/dashboards/test_dashboard.py',
            'ee/clickhouse/',
        ],
        exclude: [
            'posthog/temporal/',
            'posthog/dags/',
            'common/hogvm/python/test/',
            'posthog/test/repo_invariants/',
            'posthog/hogql_queries/',
            'posthog/hogql/',
        ],
    },
    // batch-exports and tasks used to run their temporal suites here. They now run
    // them in their own product jobs, which cost no extra infrastructure because
    // every shard already starts the temporal profile. signals/emission is listed
    // because select-tests routes it here; leaving it out under-counted the segment.
    Temporal: {
        include: ['posthog/temporal/', 'products/signals/backend/emission/'],
        exclude: [],
    },
}

// ranNodeIds, when given, restricts the sum to node ids a real run recorded.
// The union keeps entries for tests another segment ran, so the prefix rules
// alone over-count a segment by more than dead entries do.
function getSegmentDuration(segment, durations, ranNodeIds = null) {
    if (!durations) {return 0}
    const { include, exclude } = DJANGO_SEGMENTS[segment]
    let total = 0
    for (const [test, dur] of Object.entries(durations)) {
        if (!include.some((p) => test.startsWith(p))) {continue}
        if (exclude.some((p) => test.startsWith(p))) {continue}
        if (ranNodeIds && !ranNodeIds.has(test)) {continue}
        total += dur
    }
    return total
}

// Fallback shard counts used when .test_durations is missing.
const DJANGO_FALLBACK_SHARDS = { Core: 38, CorePOE: 7, Temporal: 7 }

// A shard's wall is overhead + work/shards. Sizing solves that for the shared
// TARGET_WALL_SECONDS: each shard carries (target - overhead) of work, so
// shards = ceil(work / (target - overhead)) and every shard in every lane lands
// near the same, predictable duration. Ceil, so the target is a ceiling, not an
// average.
//
// The floor on the work budget covers a pathological overhead at or above the
// target: the budget stops at half the overhead instead of going to zero or
// negative, so the shard count stays bounded.
//
// minShards: full runs keep the DJANGO_MIN_SHARDS floor, but a narrowed
// (test-selection) run may legitimately fit one shard.
function calculateShards(totalWorkSeconds, overheadSeconds, minShards = DJANGO_MIN_SHARDS) {
    // The floor stops an overhead near the target from exploding the shard
    // count. It sits at half the overhead: a floor at the full overhead pinned
    // split product shards at twice their overhead, above any target below it.
    const budget = Math.max(TARGET_WALL_SECONDS - overheadSeconds, overheadSeconds / 2, 1)
    const shards = Math.ceil(totalWorkSeconds / budget)
    return Math.max(minShards, Math.min(DJANGO_MAX_SHARDS, shards))
}

// Shards for one product. Sizing a split by work/n sizes the MEAN shard, but the
// run's wall is the MAX shard, and pytest-split cuts between tests rather than
// inside one, so size the worst chunk instead.
//
// Split the suite at half the budget. Two tests above that cannot share a shard
// at all, so each takes one and they set a floor no packing goes below. What is
// left is at most half a budget per test, so a contiguous chunk of it runs at
// most one such test past its mean, giving lightWork/n + maxLight <= budget and
// so n = ceil(lightWork / (budget - maxLight)). That denominator is at least
// half the budget, so it cannot collapse.
//
// The cuts are contiguous, so a heavy test sitting between light ones divides
// the light run rather than lifting out of it. H heavy tests leave at most H + 1
// light runs, and each run rounds up on its own, so the light side can cost H
// shards beyond its own bound. Charge that whenever any light work exists.
//
// That charge assumes a fragmentation the suite may not have, so cap the count
// at the number of tests. Past it a shard is guaranteed to collect nothing
// (pytest exit 5) and spends a runner without shortening the critical path.
//
// Reading the distribution rather than a fitted ratio ties the sizing to the
// map: a suite of heavy tests gets the shards they force, an evenly grained one
// gets none it does not need, and no constant carries a past map's error.
//
// A product whose whole suite fits one shard is not split, and the bound does
// not apply to it -- an unsplit chunk is the work itself, with nothing on top.
function productSplitShards(shape) {
    const budget = productShardBudget()
    const { work = 0, heavyCount = 0, lightWork = 0, maxLight = 0, testCount = Infinity } = shape ?? {}
    if (work <= budget) {
        return 1
    }
    const lightShards = lightWork > 0 ? Math.ceil(lightWork / (budget - maxLight)) : 0
    const fragmentation = lightWork > 0 ? heavyCount : 0
    const wanted = Math.min(heavyCount + lightShards + fragmentation, testCount)
    // The two-shard floor cannot outrank the test count: a product holding one
    // test that overruns the budget still gets one job, because the second would
    // collect nothing and splitting cannot shorten the first.
    return Math.max(Math.min(2, testCount), Math.min(DJANGO_MAX_SHARDS, wanted))
}

// Selector segment key -> Django matrix segment name.
const MATRIX_NAME_BY_SEGMENT = { core: 'Core', poe: 'CorePOE', temporal: 'Temporal' }

// Shards per segment for a narrowed run: the full matrix's per-shard budget applied to
// the selected tests' recorded seconds, so a wide selection spreads over several jobs
// instead of running to the job timeout in one. Sizing from the selection's own seconds
// keeps a skewed selection honest — picking the heavy half of a segment costs more
// shards than picking the light half. The floor is 1 rather than DJANGO_MIN_SHARDS: a
// narrow selection should stay a single job. Anything missing degrades to 1.
function selectedShards(selection) {
    const seconds = selection?.durations?.selected_seconds_by_segment ?? {}
    const shards = {}
    for (const [segment, matrixName] of Object.entries(MATRIX_NAME_BY_SEGMENT)) {
        const overhead = DJANGO_OVERHEAD_SECONDS_BY_SEGMENT[matrixName]
        shards[segment] = calculateShards(Number(seconds[segment]) || 0, overhead, 1)
    }
    return shards
}

// Counts the telemetry reports, whether or not the selection was used. Null throughout
// when the selector produced nothing to read.
function selectionMetrics(selection) {
    return {
        changed_file_count: selection?.changed_file_count ?? null,
        selected_test_count: selection?.combined?.count ?? null,
        full_run_reasons_count: selection ? (selection.ast?.full_run_reasons ?? []).length : null,
        selected_test_seconds: selection?.durations?.selected_seconds ?? null,
        skipped_test_seconds: selection?.durations?.skipped_seconds ?? null,
    }
}

// What a run with nothing selected hands each matrix leg.
function emptySegments() {
    return {
        core_files: '',
        poe_files: '',
        temporal_files: '',
        compat_files: '',
        run_poe: false,
        run_temporal: false,
        segment_shards: null,
    }
}

// An untrusted selection runs the full matrices on a ready PR and skips them on a draft,
// which is the pre-selection draft behavior: a draft has a later ready run to defer to,
// and skipping is the cheaper of the two mistakes.
function fallbackSelection(fallbackMode, reason, selection) {
    console.error(`Backend test selection not used (${reason}) — Django matrix mode=${fallbackMode}`)
    return { mode: fallbackMode, narrowed: false, skip_reason: reason, ...emptySegments(), ...selectionMetrics(selection) }
}

// Which Django tests this run should execute, and whether the product matrix may narrow.
// Pure: every input is an argument, so each branch is unit-tested rather than inferred
// from a workflow run.
//   applies        this run selects at all (a PR, off the merge queue, no force label)
//   disabled       the DISABLE_BACKEND_TEST_SELECTION kill switch
//   draft          fall back by skipping rather than by running everything
//   legacyChanged  the paths filter saw an edit under posthog/ or ee/
//   runLegacy      whether the Django suite runs, and why
//   selection      the selector's parsed output, null when it did not produce one
function decideSelection({ applies, disabled, draft, legacyChanged, runLegacy, runLegacyReason, selection }) {
    if (!applies || runLegacy === false) {
        // Nothing to narrow: either the event never selects, or the Django suite is
        // skipped outright. An empty mode leaves every consumer on its own default.
        return { mode: '', narrowed: null, skip_reason: '', ...emptySegments(), ...selectionMetrics(null) }
    }
    const fallbackMode = draft ? 'skip' : 'full'
    if (disabled) {
        // Its own reason string, so flipping the kill switch during an incident stays
        // distinguishable from a genuine cascade in the selection telemetry.
        return fallbackSelection(fallbackMode, 'disabled', selection)
    }
    if (runLegacy && runLegacyReason !== 'legacy_changed') {
        // Legacy impact was inferred from a product, contract, or schema change rather
        // than seen as a direct edit. The diff-based selector cannot see that cascade, so
        // its subset would be incomplete. A direct legacy edit is the selector's home
        // turf and is deliberately trusted — its own FULL_RUN_PATTERNS decide when a
        // legacy change is too broad to narrow.
        return fallbackSelection(fallbackMode, 'untrusted', selection)
    }
    if (!selection) {
        return fallbackSelection(fallbackMode, 'selector_error', selection)
    }
    const fullRunReasons = selection.ast?.full_run_reasons ?? []
    if (fullRunReasons.length > 0) {
        console.error(`Selector requested a full run:\n  ${fullRunReasons.join('\n  ')}`)
        return fallbackSelection(fallbackMode, 'full_run_requested', selection)
    }
    const segments = selection.combined?.segments ?? {}
    const core = segments.core ?? []
    const poe = segments.poe ?? []
    const temporal = segments.temporal ?? []
    const compat = segments.compat ?? []
    if (legacyChanged && core.length === 0 && temporal.length === 0) {
        // A diff that touched legacy code but selected no Django test at all means the
        // selector had no rule for it, not that there is nothing to run — a non-Python
        // legacy file (C++ parser sources, a JSON config) reaches no import edge.
        // Narrowing to zero would silently gate on nothing. FULL_RUN_PATTERNS covers the
        // known cases; this catches the ones added to the `legacy` paths filter and
        // forgotten there. Products-only diffs legitimately select nothing and are not legacy.
        return fallbackSelection(fallbackMode, 'empty_selection', selection)
    }
    console.error(`Selected: ${core.length} core, ${poe.length} POE-eligible, ${temporal.length} temporal, ${compat.length} compat`)
    return {
        mode: 'selected',
        narrowed: true,
        skip_reason: '',
        core_files: core.join(' '),
        poe_files: poe.join(' '),
        temporal_files: temporal.join(' '),
        compat_files: compat.join(' '),
        run_poe: poe.length > 0,
        run_temporal: temporal.length > 0,
        segment_shards: selectedShards(selection),
        ...selectionMetrics(selection),
    }
}

// The run identity the selection telemetry event carries, from the runner's own env.
function runContext() {
    let prNumber = null
    try {
        prNumber = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf-8')).pull_request?.number ?? null
    } catch {
        // Not a GitHub run, or no event payload: the fields stay null.
    }
    return {
        event_type: process.env.GITHUB_EVENT_NAME ?? null,
        branch: process.env.GITHUB_HEAD_REF || process.env.GITHUB_REF_NAME || null,
        sha: process.env.GITHUB_SHA ?? null,
        pr_number: prNumber,
        run_id: process.env.GITHUB_RUN_ID ?? null,
    }
}

function buildDjangoShards(durations, ranNodeIds = {}) {
    const result = {}
    for (const [segment] of Object.entries(DJANGO_SEGMENTS)) {
        const overhead = DJANGO_OVERHEAD_SECONDS_BY_SEGMENT[segment]
        const ran = ranNodeIds[segment] || null
        const duration = getSegmentDuration(segment, durations, ran)
        const shards = durations ? calculateShards(duration, overhead) : DJANGO_FALLBACK_SHARDS[segment]
        const wall = overhead + duration / shards
        result[segment] = { duration_seconds: duration, shards, estimated_wall_seconds: wall }
        const source = durations ? (ran ? 'auto, junit-scoped' : 'auto, union') : 'fallback'
        console.error(
            `  Django ${segment}: ${(duration / 60).toFixed(1)} min total, ${shards} shards (${source}), ~${(wall / 60).toFixed(1)} min est. wall`
        )
    }
    return result
}

// A workflow edit reaches an open PR before this script does, so an entry a
// single turbo invocation can express keeps the pre-legs {filters, pytest_args}
// keys beside its leg. An entry with several legs has no such expression and
// carries legs alone, by which point the workflow reading it is the new one.
function matrixEntry(group, legs) {
    const entry = { group, legs }
    if (legs.length === 1) {
        entry.filters = legs[0].filters
        entry.pytest_args = legs[0].pytest_args
    }
    return entry
}

function buildMatrix(products, durations, productsScaled = false) {
    const matrix = []
    const packable = []
    const fillableJobs = []

    // Split a product across multiple shards with the same rule Django uses:
    // enough shards that each lands at the shared wall target. Unlike packing,
    // the split carries no safety factor -- productSplitShards derives its own
    // headroom from the product's longest test instead. That leaves it trusting
    // the recorded sum, which holds only while the map carries
    // PRODUCTS_SCALED_MARKER: call-only durations undercount a fixture-heavy
    // suite several-fold, and sizing an unscaled sum under-shards it.
    for (const product of products) {
        const sizing = resolveProductSizing(product, durations, productsScaled)
        const { work, maxTest, staleUnionWork, staleness } = sizing
        if (staleUnionWork !== null) {
            console.error(
                `  ${product}: .test_durations stale, ${staleness.coveredCount}/${staleness.fileCount} test files covered ` +
                `(${(staleness.coverage * 100).toFixed(0)}%). Using fallback estimate: ${(work / 60).toFixed(1)} min (was ${(staleUnionWork / 60).toFixed(1)} min)`
            )
            console.error(
                `::warning title=Stale .test_durations::Product '${product}' has only ${staleness.coveredCount}/${staleness.fileCount} ` +
                `test files covered in .test_durations. Duration estimates are unreliable, using fallback sharding.`
            )
        }

        const shards = productSplitShards(sizing)
        if (shards > 1) {
            console.error(`  ${product}: ${(work / 60).toFixed(1)} min work → split across ${shards} shards`)
            const filters = `--filter=@posthog/products-${product}`
            // optimal_chunks (PostHog pytest-split fork) makes the same contiguous,
            // order-preserving cuts as duration_based_chunks but balances them
            // optimally. The greedy rule in duration_based_chunks lets every shard
            // overrun the per-shard average, which on skewed suites starves trailing
            // shards down to zero tests (pytest exit 5, "no tests collected").
            const shardCost = work / shards + maxTest
            for (let i = 1; i <= shards; i++) {
                const leg = {
                    filters,
                    pytest_args: `-- --splits ${shards} --group ${i} --splitting-algorithm optimal_chunks`,
                }
                // work/shards + maxTest bounds every shard, whichever one
                // optimal_chunks leaves lightest, so one shard can be offered to the
                // packer without knowing which. Do not tighten this to work/shards:
                // the bound is what keeps a filled shard inside the job budget.
                if (i === shards && !DEDICATED_BUCKET_PRODUCTS.has(product)) {
                    fillableJobs.push({
                        label: `${product} (${i}/${shards})`,
                        legs: [leg],
                        products: [],
                        cost: shardCost,
                        baseOverhead: PRODUCT_JOB_OVERHEAD_SECONDS,
                    })
                } else {
                    matrix.push(matrixEntry(`${product} (${i}/${shards})`, [leg]))
                }
            }
        } else if (DEDICATED_BUCKET_PRODUCTS.has(product)) {
            console.error(`  ${product}: ${(work / 60).toFixed(1)} min work → dedicated job (never shared)`)
            matrix.push(matrixEntry(product, [{ filters: `--filter=@posthog/products-${product}`, pytest_args: '' }]))
        } else {
            packable.push(product)
        }
    }

    for (const bucket of packProducts(packable, durations, productsScaled, fillableJobs)) {
        const group = [bucket.label, ...bucket.products].filter(Boolean).join(', ')
        console.error(`  job (${(bucket.cost / 60).toFixed(1)} min effective): ${group}`)
        const legs = [...bucket.legs]
        if (bucket.products.length > 0) {
            legs.push({
                filters: bucket.products.map((p) => `--filter=@posthog/products-${p}`).join(' '),
                pytest_args: '',
            })
        }
        matrix.push(matrixEntry(group, legs))
    }

    return matrix
}

// Exported for unit tests.
module.exports = {
    narrowedProducts,
    decideSelection,
    selectedShards,
    calculateShards,
    pruneDeadDurations,
    getSegmentDuration,
    getProductDuration,
    resolveProductSizing,
    buildMatrix,
    PRODUCT_JOB_OVERHEAD_SECONDS,
    PRODUCT_BUCKET_SAFETY_FACTOR,
    productSplitShards,
    getProductShape,
    PRODUCTS_SCALED_MARKER,
    TARGET_WALL_SECONDS,
    DJANGO_OVERHEAD_SECONDS_BY_SEGMENT,
    DJANGO_SEGMENTS,
    getIsolatedProducts,
    collectTestFiles,
    checkProductStaleness,
    productPrefix,
    productEffectiveCost,
    STALENESS_COVERAGE_THRESHOLD,
    STALENESS_FALLBACK_SECONDS_PER_FILE,
    productGraphFromTachMap,
    loadTachModuleGraph,
    tachDependents,
}

// --- Main ---
if (require.main === module) {

const legacyChanged = process.env.LEGACY_CHANGED === 'true'
const schemaChanged = process.env.SCHEMA_CHANGED === 'true'
const selection = loadSelection(process.env.SELECTION_JSON)

let allTestTasks, affectedTestTasks, affectedContractTasks, contractTasks
try {
    allTestTasks = parseTurboTasks(runTurbo(['run', 'backend:test', '--dry-run=json']))
    if (!legacyChanged) {
        contractTasks = parseTurboTasks(runTurbo(['run', 'backend:contract-check', '--dry-run=json']))
    }
} catch (e) {
    console.error(`turbo discovery failed: ${e.message}`)
    if (e.stderr) {
        console.error(e.stderr.toString().slice(0, 1000))
    }
    process.exit(1)
}
console.error(`Turbo affected base: ${process.env.TURBO_SCM_BASE || '(default)'}`)
console.error(`Turbo affected head: ${process.env.TURBO_SCM_HEAD || '(default)'}`)
if (!legacyChanged) {
    affectedTestTasks = queryAffectedTasks('backend:test')
    affectedContractTasks = queryAffectedTasks('backend:contract-check')
    if (affectedTestTasks === null || affectedContractTasks === null) {
        console.error('turbo discovery failed')
        process.exit(1)
    }
} else if (process.env.SELECTION_JSON) {
    // A legacy diff with a backend test selection still asks which products changed:
    // that set seeds the narrowed product matrix. A failed query only disables it.
    affectedTestTasks = queryAffectedTasks('backend:test')
}
const allProducts = getAllProducts(allTestTasks)
const allProductSet = new Set(allProducts)

let products
let runLegacy
// Why runLegacy was set, so ci-backend's test selection can tell a direct legacy edit
// (which the diff-based selector handles) from an inferred product->legacy cascade
// (which it cannot see). Empty when runLegacy is false.
let runLegacyReason = ''
// On a legacy diff the full product matrix is the fallback. Given a backend test
// selection, the matrix narrows to these products plus the ones the selector reached
// through the import graph. Null when that narrowing is not safe.
let mustRunProducts = null

if (legacyChanged) {
    console.error('Legacy code changed — testing all products')
    products = allProducts
    runLegacy = true
    runLegacyReason = 'legacy_changed'
    if (affectedTestTasks) {
        mustRunProducts = legacyMustRunProducts(affectedTestTasks, allProductSet, schemaChanged)
    }
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
        runLegacyReason = 'non_isolated_product'
    } else if (affectedProducts.length > 0) {
        // Only isolated products changed — check whether their contract surface was affected
        const affectedProductSet = new Set(affectedProducts)
        const affectedContracts = getAffectedTaskProducts(affectedContractTasks)
            .filter((p) => affectedProductSet.has(p))
        logAffectedReasons('backend:contract-check', affectedContractTasks)
        if (affectedContracts.length > 0) {
            console.error(`Isolated product contracts changed: ${JSON.stringify(affectedContracts)} — Django will run`)
            runLegacy = true
            runLegacyReason = 'contract_cascade'
            const dependents = tachDependentProducts(affectedContracts, allProductSet)
            if (dependents === null) {
                // Fail toward over-testing, like the quarantine loaders above: without the
                // graph we cannot know which products depend on the changed contract, and
                // guessing "none" silently recreates the gap this cascade exists to close.
                console.error('Dependent cascade unavailable — testing all products rather than risk skipping a dependent')
                products = allProducts
            } else {
                if (dependents.length > 0) {
                    console.error(
                        `Dependent products cascaded in via tach map: ${JSON.stringify(dependents)} (transitively depend on ${JSON.stringify(affectedContracts)})`
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
        const schemaProducts = schemaAffectedProducts()
        if (schemaProducts === null) {
            console.error('Schema diff unavailable — falling back to all products + Django')
            products = allProducts
        } else {
            products = [...new Set([...products, ...schemaProducts])].sort()
        }
        // Core (posthog/, ee/, etc.) imports schema heavily; always run Django on schema changes.
        runLegacy = true
        runLegacyReason = 'schema'
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

// Un-quarantining must re-run the suite. The ci-backend `legacy` paths-filter still
// pulls every product into the matrix on any PR touching the quarantine file, so this
// diff against the merge base rarely changes the outcome — it is the backstop that
// keeps product re-runs correct if that coarse trigger is ever narrowed (Turbo itself
// never sees .test_quarantine.json as a product input). Django's side of the same
// invariant is carried by FULL_RUN_PATTERNS in the backend test selector, since a
// legacy diff no longer implies a full Django run on its own.
const liftedProducts = []
if (process.env.TURBO_SCM_BASE) {
    const baseQuarantined = loadBaseQuarantinedSkipProducts(process.env.TURBO_SCM_BASE, todayISO)
    const allProductSet = new Set(allProducts)
    const productSet = new Set(products)
    for (const name of baseQuarantined) {
        if (quarantinedProducts.has(name) || skipProducts.has(name)) {continue}
        if (!allProductSet.has(name) || productSet.has(name)) {continue}
        console.error(`Quarantine lifted for '${name}' since ${process.env.TURBO_SCM_BASE} — forced into matrix`)
        products.push(name)
        liftedProducts.push(name)
    }
    products.sort()
}

const selectionDecision = decideSelection({
    applies: process.env.SELECTION_APPLIES === 'true',
    disabled: process.env.SELECTION_DISABLED === 'true',
    draft: process.env.PR_DRAFT === 'true',
    legacyChanged,
    runLegacy,
    runLegacyReason,
    selection,
})

// Narrow the legacy-diff matrix after every drop and lift above, so narrowing can only
// remove products. The matrix is then packed from the narrowed list.
const productCountBeforeNarrowing = products.length
let productMatrixNarrowed = false
if (mustRunProducts !== null && selectionDecision.mode === 'selected') {
    const mustRun = [...new Set([...mustRunProducts, ...liftedProducts])].sort()
    console.error(`Products that must run if the matrix is narrowed: ${JSON.stringify(mustRun)}`)
    products = narrowedProducts(products, mustRun, selection)
    productMatrixNarrowed = true
}

console.error(`Products to test: ${JSON.stringify(products)}`)
console.error(`Run legacy (Django): ${runLegacy}${runLegacyReason ? ` (${runLegacyReason})` : ''}`)

const rawDurations = loadTestDurations()
// Read before pruning: the marker's key is not a real file, so pruning drops it.
const productsScaled = Boolean(rawDurations && rawDurations[PRODUCTS_SCALED_MARKER])
if (productsScaled) {
    console.error('Product entries in .test_durations are junit-scaled, trusting their magnitudes')
}
const durations = pruneDeadDurations(rawDurations)
const ranNodeIds = loadRanNodeIds()

console.error('\nDjango shard calculation:')
const djangoShards = buildDjangoShards(durations, ranNodeIds)

const { mode, core_files, poe_files, temporal_files, compat_files, run_poe, run_temporal, segment_shards, ...metrics } =
    selectionDecision
const result = {
    matrix: buildMatrix(products, durations, productsScaled),
    run_legacy: runLegacy,
    run_legacy_reason: runLegacyReason,
    django_shards: djangoShards,
    // What the Django matrix jobs read, as one job output; segment_shards stays a JSON
    // string because build_django_matrix parses it itself.
    selection: {
        mode,
        core_files,
        poe_files,
        temporal_files,
        compat_files,
        run_poe,
        run_temporal,
        segment_shards: segment_shards ? JSON.stringify(segment_shards) : '',
    },
    // The posthog-ci-test-selection event, ready for the capture-test-selection job.
    telemetry: {
        suite: 'backend',
        mode,
        run_poe,
        run_temporal,
        ...metrics,
        run_legacy: runLegacy,
        run_legacy_reason: runLegacyReason,
        product_matrix_narrowed: productMatrixNarrowed,
        product_count: products.length,
        product_count_full: productCountBeforeNarrowing,
        ...runContext(),
    },
}
// eslint-disable-next-line no-console
process.stdout.write(JSON.stringify(result) + '\n')

} // end if (require.main === module)
