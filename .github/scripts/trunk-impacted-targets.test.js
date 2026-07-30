// Run with: node --test .github/scripts/trunk-impacted-targets.test.js
//
// Unit tests for the Trunk merge-queue target computation. Every case here
// guards the same class of bug: a target set that is narrower than reality,
// which makes Trunk merge two conflicting PRs in parallel lanes and breaks
// master. Uses synthetic products/crates/graphs throughout rather than the
// real repo layout, which would turn these into change-detector tests that
// break whenever a product or crate is added.

const test = require('node:test')
const assert = require('node:assert/strict')

const {
    computeTargets,
    globToRegExp,
    isTripwire,
    parseCrateDependencies,
    reverseClosure,
    ALL,
} = require('./trunk-impacted-targets')

const CONTEXT = {
    products: ['alpha', 'beta', 'gamma'],
    isolatedProducts: new Set(['alpha', 'beta']),
    rustGraph: {
        dependsOn: new Map([
            ['shared', []],
            ['consumer', ['shared']],
            ['unrelated', []],
        ]),
        byDir: [
            { dir: 'consumer', name: 'consumer' },
            { dir: 'unrelated', name: 'unrelated' },
            { dir: 'shared', name: 'shared' },
        ],
    },
    tachGraph: {
        graph: new Map(),
        // Mirrors turbo-discover's dashed-name contract at the boundary.
        tachDependents: (changed) => (changed.includes('alpha') ? ['beta', 'gamma'] : []),
    },
}

test('every tripwire forces ALL', () => {
    const tripwireFiles = [
        'pnpm-lock.yaml',
        'uv.lock',
        'rust/Cargo.lock',
        'tach.toml',
        '.github/workflows/ci-backend.yml',
        'proto/events.proto',
        'frontend/src/queries/schema.json',
        'posthog/schema.py',
        'products/alpha/manifest.tsx',
        'bin/start',
        '.test_durations',
    ]
    for (const file of tripwireFiles) {
        assert.equal(isTripwire(file), true, `${file} should be a tripwire`)
        assert.equal(computeTargets([file], CONTEXT), ALL, `${file} should force ALL`)
    }
})

test('a tripwire anywhere in the change set forces ALL even alongside narrow files', () => {
    assert.equal(computeTargets(['products/alpha/backend/api.py', 'pnpm-lock.yaml'], CONTEXT), ALL)
})

// The single most dangerous failure mode: an unclaimed path yielding an empty
// target set reads to Trunk as "overlaps nothing", so the PR merges in parallel
// with everything. A new top-level directory must widen, never narrow.
test('an unmapped path forces ALL rather than an empty target set', () => {
    for (const file of ['terraform/main.tf', 'some-new-toplevel/thing.go', 'common/unrecognized/x.ts']) {
        assert.equal(computeTargets([file], CONTEXT), ALL, `${file} should force ALL`)
    }
})

test('globs match across directories only through **', () => {
    assert.equal(globToRegExp('.github/**').test('.github/workflows/ci.yml'), true)
    assert.equal(globToRegExp('products/*/manifest.tsx').test('products/alpha/manifest.tsx'), true)
    // A single star must not span a separator, or products/*/manifest.tsx would
    // swallow unrelated nested paths and quietly widen every product change.
    assert.equal(globToRegExp('products/*/manifest.tsx').test('products/alpha/nested/manifest.tsx'), false)
    assert.equal(globToRegExp('Dockerfile*').test('Dockerfile.sqlx-migrate'), true)
    assert.equal(globToRegExp('pnpm-lock.yaml').test('nested/pnpm-lock.yaml'), false)
})

test('a changed rust crate pulls in the crates that depend on it', () => {
    assert.deepEqual(computeTargets(['rust/shared/src/lib.rs'], CONTEXT), ['rust:crate:consumer', 'rust:crate:shared'])
    // A leaf crate must not drag in its own dependencies, only its dependents.
    assert.deepEqual(computeTargets(['rust/consumer/src/main.rs'], CONTEXT), ['rust:crate:consumer'])
    assert.deepEqual(computeTargets(['rust/unrelated/src/main.rs'], CONTEXT), ['rust:crate:unrelated'])
})

test('an unresolvable rust crate graph reports every crate instead of narrowing', () => {
    const noGraph = { ...CONTEXT, rustGraph: null }
    assert.equal(computeTargets(['rust/shared/src/lib.rs'], noGraph), ALL)
})

test('a rust path outside every known crate forces ALL', () => {
    assert.equal(computeTargets(['rust/not-a-crate/file.rs'], CONTEXT), ALL)
})

test('reverseClosure walks transitively and excludes unrelated nodes', () => {
    const graph = new Map([
        ['base', []],
        ['mid', ['base']],
        ['top', ['mid']],
        ['island', []],
    ])
    assert.deepEqual(reverseClosure(['base'], graph).sort(), ['base', 'mid', 'top'])
    assert.deepEqual(reverseClosure(['island'], graph), ['island'])
})

// Guards the prost14 = { package = "prost" } shape: treating any renamed
// dependency as unparseable knocked out the whole rust graph, collapsing every
// rust PR into ALL.
test('renamed dependencies resolve to the real crate without failing the graph', () => {
    const crateNames = new Set(['shared', 'consumer'])
    const toml = `
[package]
name = "consumer"

[dependencies]
prost14 = { package = "prost", version = "0.14" }
aliased = { package = "shared", path = "../shared" }
shared.workspace = true
serde = "1"
`
    assert.deepEqual(parseCrateDependencies(toml, crateNames).sort(), ['shared'])
})

// Cargo spells dependency sections four ways. The [dependencies.<name>] form
// carries the name in the header, and reading only body keys silently dropped
// the edge (rust/personhog-stateright depends on personhog-coordination this
// way), which let a shared crate and its dependent get disjoint targets and
// merge in parallel.
test('dependency sections are parsed in every header form Cargo allows', () => {
    const crateNames = new Set(['shared', 'other', 'renamed-crate'])
    const cases = [
        ['plain table', '[dependencies]\nshared = { path = "../shared" }\n', ['shared']],
        ['dev table', '[dev-dependencies]\nshared.workspace = true\n', ['shared']],
        ['build table', '[build-dependencies]\nshared = "1"\n', ['shared']],
        ['dependency-per-table', '[dependencies.shared]\npath = "../shared"\nversion = "0.1"\n', ['shared']],
        ['dev dependency-per-table', '[dev-dependencies.other]\npath = "../other"\n', ['other']],
        [
            'target-scoped table',
            '[target.\'cfg(not(target_env = "msvc"))\'.dependencies]\nshared = { version = "1" }\n',
            ['shared'],
        ],
        [
            'dependency-per-table with a rename',
            '[dependencies.alias]\npackage = "renamed-crate"\npath = "../renamed-crate"\n',
            ['renamed-crate'],
        ],
        // The workspace table declares versions for every member, not this
        // crate's own edges.
        ['workspace table excluded', '[workspace.dependencies]\nshared = { path = "shared" }\n', []],
    ]
    for (const [label, toml, expected] of cases) {
        assert.deepEqual(parseCrateDependencies(toml, crateNames).sort(), expected, label)
    }
})

// Attribute keys inside a [dependencies.<name>] table would be read as
// dependency names if the body were scanned, inventing an edge to any crate
// that happens to share a name with a Cargo attribute.
test('attributes inside a dependency-per-table are not read as crate names', () => {
    const crateNames = new Set(['shared', 'path', 'features'])
    const toml = '[dependencies.shared]\npath = "../shared"\nfeatures = ["a"]\n'
    assert.deepEqual(parseCrateDependencies(toml, crateNames), ['shared'])
})

test('an isolated product change stays narrow and names its tach dependents', () => {
    assert.deepEqual(computeTargets(['products/alpha/backend/api.py'], CONTEXT), [
        'py:product:alpha',
        'py:product:beta',
        'py:product:gamma',
    ])
    // beta has no dependents in the synthetic graph, so it must not widen.
    assert.deepEqual(computeTargets(['products/beta/backend/api.py'], CONTEXT), ['py:product:beta'])
})

test('a non-isolated product change widens to every backend target', () => {
    const targets = computeTargets(['products/gamma/backend/api.py'], CONTEXT)
    assert.equal(targets.includes('py:core'), true)
    for (const product of CONTEXT.products) {
        assert.equal(targets.includes(`py:product:${product}`), true, `expected py:product:${product}`)
    }
})

test('an unavailable tach graph widens backend changes instead of narrowing', () => {
    const noTach = { ...CONTEXT, tachGraph: null }
    const targets = computeTargets(['products/alpha/backend/api.py'], noTach)
    assert.equal(targets.includes('py:core'), true)
    assert.equal(targets.includes('py:product:gamma'), true)
})

// Core changes have to overlap every leaf in their domain, because set
// intersection is the only way Trunk can express "this can break anything
// downstream".
test('core changes expand to every leaf target in their own domain', () => {
    const backend = computeTargets(['posthog/models/team.py'], CONTEXT)
    assert.deepEqual(backend, ['py:core', 'py:product:alpha', 'py:product:beta', 'py:product:gamma'])

    const frontend = computeTargets(['frontend/src/lib/components/Foo.tsx'], CONTEXT)
    assert.deepEqual(frontend, ['fe:core', 'fe:product:alpha', 'fe:product:beta', 'fe:product:gamma'])
})

test('product frontend and backend changes land in separate domains', () => {
    assert.deepEqual(computeTargets(['products/alpha/frontend/Scene.tsx'], CONTEXT), ['fe:product:alpha'])
    assert.deepEqual(computeTargets(['products/beta/backend/api.py'], CONTEXT), ['py:product:beta'])
})

test('a product file that is neither backend nor frontend claims both domains', () => {
    const targets = computeTargets(['products/beta/mcp/tools.yaml'], CONTEXT)
    assert.equal(targets.includes('py:product:beta'), true)
    assert.equal(targets.includes('fe:product:beta'), true)
})

// tools/ is not one bucket. phrocs is Go with its own CI and nothing imports
// it, while hogli-commands is loaded by posthog/conftest.py on every pytest
// run, so lumping them together either serializes phrocs needlessly or hands
// hogli a lane it must not have.
test('independently testable tools get their own lane', () => {
    assert.deepEqual(computeTargets(['tools/phrocs/internal/tui/app.go'], CONTEXT), ['tools:phrocs'])
    assert.deepEqual(computeTargets(['tools/traffic-sim/main.go'], CONTEXT), ['tools:traffic-sim'])
})

test('backend-coupled and unrecognized tools stay in the backend lanes', () => {
    for (const file of [
        'tools/hogli/cli.py',
        'tools/hogli-commands/hogli_commands/quarantine/core.py',
        // A tool nobody has classified yet must over-report rather than be
        // handed a lane it has not earned.
        'tools/some-new-tool/main.py',
    ]) {
        const targets = computeTargets([file], CONTEXT)
        assert.equal(targets.includes('py:core'), true, `${file} should widen to the backend lanes`)
    }
})

// These steer what every suite runs, so they cannot sit in one domain's lane.
test('CI-steering scripts directly under tools/ force ALL', () => {
    assert.equal(computeTargets(['tools/playwright_spec_selection.py'], CONTEXT), ALL)
    assert.equal(computeTargets(['tools/snob_backend_test_selection_shadow.py'], CONTEXT), ALL)
})

// Both sit on the fe/py boundary: openapi-codegen generates the frontend types
// from backend serializers, and owners is read by both suites.
test('cross-domain tools are tripwires rather than backend-only', () => {
    assert.equal(computeTargets(['tools/openapi-codegen/config.ts'], CONTEXT), ALL)
    assert.equal(computeTargets(['tools/owners/owners/__init__.py'], CONTEXT), ALL)
})

test('markdown is classified as docs regardless of which tree it sits in', () => {
    assert.deepEqual(computeTargets(['posthog/README.md', 'docs/guide.mdx'], CONTEXT), ['docs'])
})

test('independent trees stay disjoint so they can share no lane', () => {
    const rust = computeTargets(['rust/unrelated/src/main.rs'], CONTEXT)
    const node = computeTargets(['nodejs/src/worker.ts'], CONTEXT)
    const service = computeTargets(['services/mcp/src/index.ts'], CONTEXT)
    const docs = computeTargets(['docs/guide.md'], CONTEXT)

    const sets = [rust, node, service, docs]
    for (let i = 0; i < sets.length; i++) {
        for (let j = i + 1; j < sets.length; j++) {
            const overlap = sets[i].filter((target) => sets[j].includes(target))
            assert.deepEqual(overlap, [], `${sets[i]} and ${sets[j]} must not overlap`)
        }
    }
})

// Playwright specs run against whatever frontend lands beside them, so they
// have to share the frontend lanes rather than forming an island.
test('playwright changes overlap the frontend domain', () => {
    const specs = computeTargets(['playwright/e2e/login.spec.ts'], CONTEXT)
    const frontend = computeTargets(['frontend/src/lib/components/Foo.tsx'], CONTEXT)
    assert.equal(
        specs.some((target) => frontend.includes(target)),
        true
    )
})
