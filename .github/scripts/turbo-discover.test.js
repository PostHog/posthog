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
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { DJANGO_SEGMENTS, getIsolatedProducts } = require('./turbo-discover')

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
