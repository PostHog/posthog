// Run with: node --test .github/scripts/turbo-discover.test.js
//
// Pins turbo-discover's DJANGO_SEGMENTS table to the Django pytest invocations
// in ci-backend.yml. The table sizes the shards each segment gets, so a segment
// listing paths the workflow no longer runs (or missing ones it does) budgets
// wall time for a run that never happens. Both workflow copies are read: the
// Depot mirror runs the same matrix and drifts on its own.
//
// Reads the workflow rather than a fixture on purpose — the workflow is the one
// side that can drift, and there is nothing else to compare the table against.

const test = require('node:test')
const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
    DJANGO_SEGMENTS,
    getIsolatedProducts,
    getTestOnlyProducts,
    changedFilesSinceBase,
} = require('./turbo-discover')

const REPO_ROOT = path.join(__dirname, '..', '..')
const WORKFLOWS = ['.github/workflows/ci-backend.yml', '.depot/workflows/ci-backend.yml']

// pytest takes `./posthog/queries/` and `posthog` for the same directory, and
// --ignore drops the trailing slash. DJANGO_SEGMENTS stores prefixes, so every
// spelling has to land on the same one. File targets keep their extension.
function toPrefix(target) {
    const cleaned = target.replace(/^\.\//, '').replace(/\/$/, '')
    return cleaned.endsWith('.py') ? cleaned : `${cleaned}/`
}

function sorted(prefixes) {
    return [...new Set(prefixes)].sort()
}

function section(text, startMarker, endMarker) {
    const start = text.indexOf(startMarker)
    assert.notEqual(start, -1, `missing ${startMarker}`)
    const end = text.indexOf(endMarker, start)
    assert.notEqual(end, -1, `missing ${endMarker}`)
    return text.slice(start, end)
}

function matchAll(text, pattern) {
    return [...text.matchAll(pattern)].map((match) => match[1])
}

// The Core step runs both matrix legs: `full_targets` is reassigned per leg and
// the person-on-events leg adds its own ignores on top of the shared ones. The
// compat leg reads its targets from an env var, so it has no literal to pick up.
function parseCoreStep(text) {
    const step = section(text, 'full_targets="posthog ee/"', '--junitxml=junit-core.xml')
    const targets = matchAll(step, /full_targets="([^"]*)"/g).filter((value) => !value.startsWith('$'))
    assert.equal(targets.length, 2, 'expected a Core and a person-on-events full_targets assignment')
    const [core, poe] = targets.map((value) => value.trim().split(/\s+/))
    const poeIgnoreLine = step.match(/full_ignores\+=\(([^)]*)\)/)
    return {
        core,
        poe,
        ignores: matchAll(step.replace(/full_ignores\+=\([^)]*\)/g, ''), /--ignore=(\S+)/g),
        poeIgnores: poeIgnoreLine ? matchAll(poeIgnoreLine[1], /--ignore=(\S+)/g) : [],
    }
}

function parseTemporalTargets(text) {
    const invocation = text.match(/pytest [^\n]*junit_duration_report=call (posthog\/temporal[^\n]*?) -m /)
    assert.notEqual(invocation, null, 'missing the full Temporal pytest invocation')
    return invocation[1].split(/\s+/)
}

for (const workflow of WORKFLOWS) {
    const text = fs.readFileSync(path.join(REPO_ROOT, workflow), 'utf8')
    const core = parseCoreStep(text)
    const expected = {
        Core: { include: core.core, exclude: core.ignores },
        CorePOE: { include: core.poe, exclude: [...core.ignores, ...core.poeIgnores] },
        Temporal: { include: parseTemporalTargets(text), exclude: [] },
    }

    for (const [segment, paths] of Object.entries(expected)) {
        test(`${segment} segment matches the pytest targets in ${workflow}`, () => {
            assert.deepEqual(sorted(DJANGO_SEGMENTS[segment].include), sorted(paths.include.map(toPrefix)))
            assert.deepEqual(sorted(DJANGO_SEGMENTS[segment].exclude), sorted(paths.exclude.map(toPrefix)))
        })
    }
}

// The backend test selector is the third copy of the partition: it routes each
// selected test file to a segment, so a prefix it no longer shares with the pytest
// invocation sends selected tests to a leg that ignores them. Its prefix tuples are
// plain literals, read here the same way the workflow is.
const SELECTOR = 'tools/snob_backend_test_selection_shadow.py'

function pythonTuple(text, name) {
    const match = text.match(new RegExp(`${name} = \\(([^)]*)\\)`))
    assert.notEqual(match, null, `missing ${name} in ${SELECTOR}`)
    return matchAll(match[1], /"([^"]+)"/g)
}

test('the backend test selector routes files with the same partition', () => {
    const text = fs.readFileSync(path.join(REPO_ROOT, SELECTOR), 'utf8')
    const temporal = pythonTuple(text, '_TEMPORAL_PREFIXES')
    const poe = [...pythonTuple(text, '_POE_PREFIXES'), ...matchAll(text, /path == "([^"]+)"/g)]
    const ignored = pythonTuple(text, '_CORE_IGNORED_PREFIXES')

    assert.deepEqual(sorted(temporal), sorted(DJANGO_SEGMENTS.Temporal.include))
    assert.deepEqual(sorted(poe), sorted(DJANGO_SEGMENTS.CorePOE.include))
    // The selector checks the temporal prefixes first, so Core's exclusion of
    // them is implicit there and explicit in the table.
    const claimedFromCore = temporal.filter((prefix) =>
        DJANGO_SEGMENTS.Core.include.some((include) => prefix.startsWith(include))
    )
    assert.deepEqual(sorted([...ignored, ...claimedFromCore]), sorted(DJANGO_SEGMENTS.Core.exclude))
})

// CorePOE re-runs a slice of Core under the legacy joined person mode, and Core
// runs the same files under the customer-default mode. A CorePOE path outside
// Core's pool therefore runs in the legacy mode only, so a regression under the
// mode customers use goes uncaught. Product tests belong in the product's own
// turbo lane, which is where that path would otherwise be reaching for coverage.
// An include Core also ignores is no better than one it never listed, so both
// halves have to hold. A Core ignore NESTED inside a CorePOE path needs no check:
// CorePOE's ignores are Core's plus its own, so that subtree is out of both legs.
test("the safeguard allowlist stays inside Core's pool", () => {
    for (const prefix of DJANGO_SEGMENTS.CorePOE.include) {
        const included = DJANGO_SEGMENTS.Core.include.some((include) => prefix.startsWith(include))
        const excluded = DJANGO_SEGMENTS.Core.exclude.some((exclude) => prefix.startsWith(exclude))
        assert.ok(
            included && !excluded,
            `${prefix} is in CorePOE but Core does not run it, so it never runs in the default person mode`
        )
    }
})

// Isolation is the claim that a product can be tested without the Django suite.
// A product that ships the contract-check script but no turbo.json of its own
// leaves the task on the root definition, whose inputs are its whole backend,
// so every backend edit reads as a contract change and cascades anyway.
test('isolation needs both the contract-check script and narrowed contract inputs', () => {
    const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'isolated-products-'))
    const declare = (product, turboJson) => {
        fs.mkdirSync(path.join(repoRoot, 'products', product), { recursive: true })
        if (turboJson) {
            fs.writeFileSync(path.join(repoRoot, 'products', product, 'turbo.json'), JSON.stringify(turboJson))
        }
    }
    declare('declared', { tasks: { 'backend:contract-check': { inputs: ['backend/facade/**'] } } })
    declare('empty-inputs', { tasks: { 'backend:contract-check': { inputs: [] } } })
    declare('other-task', { tasks: { 'backend:test': { inputs: ['backend/**'] } } })
    declare('no-turbo-json', null)
    // Directory uses underscores while the package name uses dashes — the lookup
    // must bridge the two or every multiword product reads as non-isolated.
    declare('multi_word', { tasks: { 'backend:contract-check': { inputs: ['backend/facade/**'] } } })

    // Every task here comes from `turbo run backend:contract-check`, so each of
    // these products already declares the script.
    const tasks = ['declared', 'empty-inputs', 'other-task', 'no-turbo-json', 'multi-word'].map((product) => ({
        package: `@posthog/products-${product}`,
    }))

    assert.deepEqual([...getIsolatedProducts(tasks, repoRoot)].sort(), ['declared', 'multi-word'])
})

test('test-only product changes select only their product suites', () => {
    const importedBy = (fileMap) => (file) => fileMap[file] || []
    const nothingImportsIt = importedBy({})

    assert.deepEqual(
        getTestOnlyProducts(
            [
                'products/experiments/backend/test/test_migration_0035.py',
                'products/experiments/stats/tests/test_statistics.py',
            ],
            nothingImportsIt
        ),
        ['experiments']
    )
    assert.equal(getTestOnlyProducts(['products/experiments/backend/models/experiment.py'], nothingImportsIt), null)
    assert.equal(getTestOnlyProducts(['products/experiments/package.json'], nothingImportsIt), null)

    // A base class under a test directory is the product's behavior to every
    // suite that imports it, so narrowing to the owning product would run
    // everything except the suite that breaks.
    const base = 'products/experiments/backend/hogql_queries/test/experiment_query_runner/base.py'
    assert.equal(
        getTestOnlyProducts([base], importedBy({ [base]: ['posthog/temporal/experiments/test_cache_warming.py'] })),
        null
    )
    assert.equal(
        getTestOnlyProducts([base], importedBy({ [base]: ['products/workflows/backend/api/test/test_hog_flow.py'] })),
        null
    )
    // An importer inside the owning product is the case the shortcut exists for.
    assert.deepEqual(
        getTestOnlyProducts([base], importedBy({ [base]: ['products/experiments/backend/test/test_mean_metric.py'] })),
        ['experiments']
    )
    // No tach map, or a file the head tree no longer has: importers unknown.
    assert.equal(getTestOnlyProducts([base], () => null), null)
})

// Git reports a pure move as its new path alone, which reads as a test-only
// change while the production module the move removed is still imported from
// elsewhere. The pure-function cases above cannot see this: the hole is in the
// diff that feeds them, so this one runs the real diff over a real move.
test('a production module moved into a test directory is not a test-only change', () => {
    const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'moved-into-test-'))
    const git = (...args) => execFileSync('git', args, { cwd: repoRoot, encoding: 'utf-8' }).trim()
    const write = (file) => {
        fs.mkdirSync(path.join(repoRoot, path.dirname(file)), { recursive: true })
        fs.writeFileSync(path.join(repoRoot, file), 'X = 1\n')
    }
    // commit-tree rather than commit, so the commits need no identity beyond the
    // local config and no hook can refuse them.
    const commit = (message, parent) => {
        const parentArgs = parent ? ['-p', parent] : []
        return git('commit-tree', git('write-tree'), ...parentArgs, '-m', message)
    }

    git('init', '-q', '.')
    git('config', 'user.email', 'ci@example.com')
    git('config', 'user.name', 'ci')
    write('products/foo/backend/models/helper.py')
    git('add', '-A')
    const base = commit('add the helper')
    fs.rmSync(path.join(repoRoot, 'products/foo/backend/models/helper.py'))
    write('products/foo/backend/tests/helper.py')
    git('add', '-A')
    const head = commit('move the helper under tests', base)

    const scm = { base: process.env.TURBO_SCM_BASE, head: process.env.TURBO_SCM_HEAD }
    try {
        process.env.TURBO_SCM_BASE = base
        process.env.TURBO_SCM_HEAD = head
        const changed = changedFilesSinceBase(repoRoot)
        assert.deepEqual(changed.sort(), [
            'products/foo/backend/models/helper.py',
            'products/foo/backend/tests/helper.py',
        ])
        assert.equal(
            getTestOnlyProducts(changed, () => []),
            null
        )
    } finally {
        for (const [name, value] of [['TURBO_SCM_BASE', scm.base], ['TURBO_SCM_HEAD', scm.head]]) {
            if (value === undefined) {
                delete process.env[name]
            } else {
                process.env[name] = value
            }
        }
        fs.rmSync(repoRoot, { recursive: true, force: true })
    }
})
