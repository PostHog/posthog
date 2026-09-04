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
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
    computeTargets,
    allKnownTargets,
    buildContext,
    parseRustAffectedCrates,
    compileContractMatcher,
    compileWorkspaceMatcher,
    globToRegExp,
    isProductDirectory,
    isTripwire,
    listIsolatedProducts,
    loadContractSurfaces,
    parseCrateName,
    parsePytestIgnores,
    parseSemgrepLanguages,
    parseWorkspacePackageGlobs,
    semgrepDomain,
    tripwireDomain,
    ALL,
    JAVASCRIPT,
    NATIVE_BINDING_CONSUMER_LANES,
    NODE,
    PROTO_TREES,
    PYTHON,
    REPO_ROOT,
    RUST,
    UNIVERSAL,
} = require('./trunk-impacted-targets')
const { tachDependents } = require('./turbo-discover')

const CONTEXT = {
    products: ['alpha', 'beta', 'gamma'],
    services: ['mcp', 'oauth-proxy'],
    isolatedProducts: new Set(['alpha', 'beta']),
    semgrepDomains: new Map([
        ['.semgrep/rules/security/py-rule.yaml', PYTHON],
        ['.semgrep/rules/devex/ts-rule.yaml', JAVASCRIPT],
        ['.semgrep/rules/devex/generic-rule.yaml', UNIVERSAL],
    ]),
    rustInventory: {
        crateNames: new Set(['shared', 'consumer', 'unrelated']),
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

// What a widening decision now uploads in place of the "ALL" sentinel.
const EVERYTHING = allKnownTargets(CONTEXT)

// A graph the tach map walked all three products into, so their importer sets
// are known. The base CONTEXT deliberately holds none, which covers the case
// where a product sits outside the map and has to keep widening. Keys and
// values are product directory names, the shape productGraphFromTachMap emits.
const TACH_DECLARED_CONTEXT = {
    ...CONTEXT,
    tachGraph: {
        graph: new Map([
            ['alpha', []],
            ['beta', ['gamma']],
            ['gamma', []],
        ]),
        tachDependents,
    },
}

// PROTO_TREES names the crates that compile each tree, so the crate half of
// this inventory has to carry their real names. The dependent and the
// bystander are synthetic, which is what keeps the assertions off the real
// crate workspace.
const PROTO_CRATES = [
    'cymbal-proto',
    'ingestion-worker-proto',
    'kafka-assigner-proto',
    'personhog-proto',
    'personhog-consumer',
    'prometheus-rw-proto',
    'usage-ingestion-proto',
    'unrelated',
]
const PROTO_CONTEXT = {
    ...CONTEXT,
    rustInventory: {
        crateNames: new Set(PROTO_CRATES),
        byDir: PROTO_CRATES.map((name) => ({ dir: name, name })),
    },
}

const PROTO_EVERYTHING = allKnownTargets(PROTO_CONTEXT)

// gamma vendors its own pnpm workspace; alpha and beta keep the conventional
// backend/ + frontend/ layout, so the cases above stay on the old behavior.
const WORKSPACE_CONTEXT = {
    ...CONTEXT,
    productWorkspaces: new Map([['gamma', compileWorkspaceMatcher(['apps/*', 'packages/*', 'tooling/*'])]]),
}

// Nothing here has a blast radius the script can hold to one language: the
// lockfiles span the whole pnpm and uv workspaces, the schemas land on both
// sides of the fe/py split, and the rest steer what every suite runs or what it
// runs against.
test('a universal tripwire claims every known target', () => {
    const tripwireFiles = [
        // Runs in backend, frontend, nodejs, and rust CI alike.
        'bin/download-mmdb',
        // The stack every suite tests against, the rust integration suites
        // included.
        'docker-compose.base.yml',
        // Trees that steer what every suite runs or what it runs against: the
        // Depot shadow of an action every workflow uses, the toolchain, the
        // service configs the stack mounts, and the markdownlint config every
        // tree's prose obeys.
        '.depot/actions/pnpm-install/action.yml',
        '.flox/env/manifest.toml',
        'docker/clickhouse/config.d/default.xml',
        'devenv/duckgres.yaml',
        '.config/.markdownlint-cli2.jsonc',
        // A workflow nobody has placed in a domain keeps the old radius.
        '.github/workflows/ci-security.yaml',
    ]
    for (const file of tripwireFiles) {
        assert.equal(isTripwire(file), true, `${file} should be a tripwire`)
        assert.deepEqual(computeTargets([file], CONTEXT), EVERYTHING, `${file} should claim every target`)
    }
})

// The lane rules and the graphs they read are the one case that must stay
// universal on principle rather than for want of a narrower radius: two PRs
// that disagree about the partition cannot be safely placed in it. Same
// self-gating hazard as CONTRACT_DECLARATIONS.
test('a change to the lane rules themselves stays universal', () => {
    for (const file of [
        '.github/scripts/trunk-impacted-targets.js',
        '.github/scripts/trunk-impacted-targets.test.js',
        '.github/scripts/trunk-lane-telemetry.js',
        '.github/scripts/turbo-discover.js',
        '.github/workflows/trunk-impacted-targets.yml',
        'turbo.json',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), EVERYTHING, file)
    }
})

// tach.toml is read by the lane rules too, so it carries the same hazard, but
// the only lanes its graph can move are python ones. Claiming them all still
// overlaps any PR whose lanes were computed against the previous graph.
test('the tach graph claims the python lanes rather than every lane', () => {
    assert.deepEqual(computeTargets(['tach.toml'], CONTEXT), computeTargets(['mypy.ini'], CONTEXT))
})

// A pnpm resolution change can red the python suites, which run through
// `pnpm turbo run backend:test`, but the PR's own CI run is what catches that.
// The interaction a lane exists to prevent needs a second PR editing the same
// lockfile, which git already stops as a textual conflict. The python side is
// the mirror image, and neither workspace resolves against the other's files.
// Only the root files narrow: a product's own manifests keep the product's lanes.
test('a lockfile claims its own toolchain rather than every lane', () => {
    for (const file of ['pnpm-lock.yaml', 'pnpm-workspace.yaml', 'package.json']) {
        assert.deepEqual(computeTargets([file], CONTEXT), computeTargets(['.oxlintrc.json'], CONTEXT), file)
    }
    for (const file of ['uv.lock', 'pyproject.toml']) {
        assert.deepEqual(computeTargets([file], CONTEXT), computeTargets(['mypy.ini'], CONTEXT), file)
    }
    assert.equal(computeTargets(['products/alpha/package.json'], CONTEXT).includes('py:product:alpha'), true)
})

// Every consumer of a proto commits the stubs generated from it, so the set is
// enumerable rather than open-ended: tonic for the crate, and checked-in
// personhog stubs for python and nodejs. The rust half is the determinator's
// answer for the diff (the crate that compiles the tree plus its dependents),
// not every crate.
test('a proto claims the consumers that generate from it rather than every lane', () => {
    const targets = computeTargets(['proto/personhog/types/v1/person.proto'], {
        ...PROTO_CONTEXT,
        rustAffectedCrates: ['personhog-proto', 'personhog-consumer'],
    })
    for (const target of [
        'py:core',
        'py:product:alpha',
        'node:ingestion',
        'rust:crate:personhog-proto',
        'rust:crate:personhog-consumer',
    ]) {
        assert.equal(targets.includes(target), true, target)
    }
    for (const target of ['fe:core', 'svc:mcp', 'rust:crate:cymbal-proto', 'rust:crate:unrelated']) {
        assert.equal(targets.includes(target), false, target)
    }

    const generatedDirs = [
        'posthog/personhog_client/proto/generated',
        'nodejs/src/common/generated/personhog',
        'rust/personhog-proto',
    ]
    for (const dir of generatedDirs) {
        assert.equal(fs.existsSync(path.join(REPO_ROOT, dir)), true, `${dir} is the stub tree its lane stands for`)
    }
})

// The narrowing the per-tree table buys: a tree nothing outside rust/ generates
// from used to serialize against every python lane in the repo.
test('a proto tree with no stubs outside rust claims neither python nor nodejs', () => {
    assert.deepEqual(
        computeTargets(['proto/cymbal/resolution/v1/resolution.proto'], {
            ...PROTO_CONTEXT,
            rustAffectedCrates: ['cymbal-proto'],
        }),
        ['rust:crate:cymbal-proto']
    )
    assert.deepEqual(
        computeTargets(['proto/kafka_assigner/v1/service.proto'], {
            ...PROTO_CONTEXT,
            rustAffectedCrates: ['kafka-assigner-proto'],
        }),
        ['rust:crate:kafka-assigner-proto']
    )
})

// buf's lint and breaking-change settings sit at the root and govern every
// tree, so a file there can break any consumer of any of them.
test('proto configuration at the root claims every tree', () => {
    const union = new Set()
    for (const file of [
        'proto/personhog/types/v1/person.proto',
        'proto/cymbal/resolution/v1/resolution.proto',
        'proto/ingestion/worker/v1/worker.proto',
        'proto/kafka_assigner/v1/service.proto',
        'proto/prometheus/v1/remote_write.proto',
        'proto/usage_ingestion/v1/service.proto',
    ]) {
        for (const target of computeTargets([file], PROTO_CONTEXT)) {
            union.add(target)
        }
    }
    assert.deepEqual(computeTargets(['proto/buf.yaml'], PROTO_CONTEXT), [...union].sort())
})

// The two ways the table can go stale. Both are the under-reporting direction —
// a tree whose consumers are unknown, and a crate the table can no longer
// find — so both widen rather than claiming the lanes they can still name.
test('an undeclared proto tree or a renamed proto crate widens', () => {
    assert.deepEqual(computeTargets(['proto/newthing/v1/service.proto'], PROTO_CONTEXT), PROTO_EVERYTHING)

    const renamed = {
        ...PROTO_CONTEXT,
        rustInventory: {
            ...PROTO_CONTEXT.rustInventory,
            crateNames: new Set([...PROTO_CONTEXT.rustInventory.crateNames].filter((c) => c !== 'personhog-proto')),
        },
    }
    assert.deepEqual(computeTargets(['proto/personhog/types/v1/person.proto'], renamed), allKnownTargets(renamed))
})

// The table is declared rather than derived, so the tree it describes has to
// fail here when it moves. Reads the real repo for that reason: the crate half
// comes from the build.rs that compiles each tree, which is the same file tonic
// reads, so a tree compiled by a second crate or by a renamed one shows up.
test('every proto tree is declared, with the crate that compiles it', () => {
    const trees = fs
        .readdirSync(path.join(REPO_ROOT, 'proto'), { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
    assert.deepEqual(trees.sort(), [...PROTO_TREES.keys()].sort())

    const compiledBy = new Map()
    const walk = (dir, depth) => {
        if (depth > 3) {
            return
        }
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name)
            if (entry.isDirectory() && entry.name !== 'target' && !entry.name.startsWith('.')) {
                walk(full, depth + 1)
                continue
            }
            if (entry.name !== 'build.rs') {
                continue
            }
            const text = fs.readFileSync(full, 'utf8')
            const referenced = [...text.matchAll(/\{proto_root\}\/([A-Za-z0-9_]+)\//g)].map((match) => match[1])
            if (referenced.length === 0) {
                // The three build scripts share the {proto_root}/<tree>/ idiom
                // the regex above keys on. One that compiles protos some other
                // way would read as compiling none, so it fails here rather
                // than leaving its tree looking unclaimed by any crate.
                assert.equal(
                    text.includes('compile_protos'),
                    false,
                    `${full} compiles protos the derivation cannot see`
                )
                continue
            }
            const crate = parseCrateName(fs.readFileSync(path.join(dir, 'Cargo.toml'), 'utf8'))
            for (const tree of referenced) {
                compiledBy.set(tree, [...new Set([...(compiledBy.get(tree) || []), crate])].sort())
            }
        }
    }
    walk(path.join(REPO_ROOT, 'rust'), 0)

    for (const [tree, { crates }] of PROTO_TREES) {
        assert.deepEqual(compiledBy.get(tree), [...crates].sort(), `crates compiling proto/${tree}`)
    }
})

// The other half of the same guard. It reads the two roots the checked-in stubs
// land in today, so a tree that starts generating into one of them without
// declaring the domain fails here. A consumer that generates into a root
// neither of these names is still only caught by review.
//
// The equality runs both ways. Reading only from the table cannot see a stub
// directory no tree claims, because a tree whose directory name differs from
// its own name (usage_ingestion generates into usage-ingestion) reads as "no
// stubs" and agrees with an empty domain list. The directory side catches that.
test('every proto tree declaring a stub consumer has stubs there, and no other tree does', () => {
    const stubRoots = [
        ['posthog/personhog_client/proto/generated', PYTHON],
        ['nodejs/src/common/generated', NODE],
    ]
    for (const [root, domain] of stubRoots) {
        const generated = fs
            .readdirSync(path.join(REPO_ROOT, root), { withFileTypes: true })
            .filter((entry) => entry.isDirectory())
            // __pycache__ is a build artifact of the python root, not a stub tree.
            .filter((entry) => !entry.name.startsWith('__'))
            .map((entry) => entry.name)
        const claimed = new Set()
        for (const [tree, { domains, stubDir }] of PROTO_TREES) {
            assert.equal(
                generated.includes(stubDir || tree),
                domains.includes(domain),
                `proto/${tree} stubs in ${root} must match its declared ${domain} consumer`
            )
            if (domains.includes(domain)) {
                claimed.add(stubDir || tree)
            }
        }
        assert.deepEqual(
            generated.filter((dir) => !claimed.has(dir)),
            [],
            `every directory in ${root} must belong to a proto tree declaring its ${domain} consumer`
        )
    }
})

// A tripwire held to one language claims every lane running that language and
// nothing else, which is the whole point: a frontend lint rule no longer
// serializes against Rust, and a backend one no longer serializes against the
// frontend.
test('a language-scoped tripwire claims only that language', () => {
    const javascript = computeTargets(['.oxlintrc.json'], CONTEXT)
    assert.equal(javascript.includes('fe:core'), true)
    assert.equal(javascript.includes('fe:product:alpha'), true)
    assert.equal(javascript.includes('node:ingestion'), true)
    assert.equal(javascript.includes('svc:mcp'), true)
    assert.equal(javascript.includes('py:core'), false)
    assert.equal(
        javascript.some((target) => target.startsWith('rust:crate:')),
        false
    )

    const python = computeTargets(['mypy.ini'], CONTEXT)
    assert.equal(python.includes('py:core'), true)
    assert.equal(python.includes('py:product:alpha'), true)
    assert.equal(python.includes('fe:core'), false)
    assert.equal(python.includes('node:ingestion'), false)

    const rust = computeTargets(['.github/workflows/ci-rust.yml'], CONTEXT)
    assert.deepEqual(rust, ['rust:crate:consumer', 'rust:crate:shared', 'rust:crate:unrelated'])
})

// A manifest is the one input both sides read: the frontend merges every
// manifest's urls and tree items into globals any product can reference, and
// products.json is generated from all of them for posthog/products.py. So it
// takes both lane families in full and stops there — no rust crate, service, or
// nodejs suite reads either file.
test('a product manifest claims the frontend and python lanes together', () => {
    const manifest = computeTargets(['products/alpha/manifest.tsx'], CONTEXT)
    assert.deepEqual(computeTargets(['frontend/src/products.json'], CONTEXT), manifest)

    for (const target of ['fe:core', 'fe:product:beta', 'py:core', 'py:product:beta']) {
        assert.equal(manifest.includes(target), true, target)
    }
    // The frontend half cannot narrow to alpha: beta's frontend can reference
    // what alpha's manifest declares, through the merged urls object.
    assert.equal(manifest.includes('fe:product:alpha'), true)
    // services/mcp/scripts walks the manifests for the routes its tool-name lint
    // checks against, so it is a reader and keeps its lane.
    assert.equal(manifest.includes('svc:mcp'), true)
    assert.equal(manifest.includes('cli'), true)
    assert.notDeepEqual(manifest, EVERYTHING)
    for (const target of ['node:ingestion', 'svc:oauth-proxy', 'rust:crate:shared']) {
        assert.equal(manifest.includes(target), false, target)
    }
    // The independent tools/ lanes ride along with any other Python tripwire,
    // and none of those tools reads a manifest or products.json.
    assert.equal(
        manifest.some((target) => target.startsWith('tools:')),
        false
    )
})

// The manifest is the file a person edits, and it already claims both families.
// These are compiled from it and carry no Python reader, so the frontend rule's
// radius is the honest one.
test('the generated frontend product artifacts claim only the frontend lanes', () => {
    const generated = computeTargets(['frontend/src/products.tsx', 'frontend/src/productScenes.tsx'], CONTEXT)
    assert.equal(generated.includes('fe:core'), true)
    assert.equal(generated.includes('fe:product:alpha'), true)
    assert.equal(generated.includes('py:core'), false)
})

// A workflow decides which suites run, so the suite it defines is the radius.
// ci-frontend.yml was the single most common reason a PR widened.
// Configuration files at the repository root are the other half of the same
// story the workflows tell: a tool's own settings can only fail the code that
// tool reads, so they no longer serialize a PR against the whole repo.
test('single-language root configuration claims that language', () => {
    const javascript = computeTargets(['.oxlintrc.json'], CONTEXT)
    for (const file of ['postcss.config.js', '.stylelintrc.js', '.stylelintignore', '.kearc', 'posthog.json']) {
        assert.deepEqual(computeTargets([file], CONTEXT), javascript, file)
    }
    const python = computeTargets(['mypy.ini'], CONTEXT)
    for (const file of ['manage.py', 'pytest_boot_gc.py', 'dagster_cloud.yaml', 'unit.json.tpl']) {
        assert.deepEqual(computeTargets([file], CONTEXT), python, file)
    }
})

// Root files whose reader is the stack, the image, or the ownership data every
// suite runs on. The narrowing above stops here: these keep the full set, but
// by decision rather than for want of a rule.
test('stack and image configuration at the root stays universal', () => {
    for (const file of ['.env.development', '.env.services', '.envrc', 'otel-collector-config.dev.yaml']) {
        assert.equal(tripwireDomain(file), UNIVERSAL, file)
        assert.deepEqual(computeTargets([file], CONTEXT), EVERYTHING, file)
    }
})

// No suite's outcome depends on ownership data jointly with a second PR: the
// root owners.yaml is a fallback, so nothing can become unowned, and the other
// readers are review-routing bots. Two ownership edits still serialize against
// each other on the shared lane.
test('ownership data shares one lane instead of every lane', () => {
    for (const file of [
        'owners.yaml',
        'tools/owners/posthog_owners/matcher.py',
        '.github/CODEOWNERS',
        '.github/owners.yaml',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['ownership'], file)
    }
    // A product's own ownership file keeps its product lane.
    assert.notDeepEqual(computeTargets(['products/alpha/owners.yaml'], CONTEXT), ['ownership'])
})

// Every quarantine reader (pytest, jest, playwright, and turbo-discover's
// product-skip input) sits inside the two language families; no rust suite
// consumes the list, so a flaky-test quarantine no longer serializes rust PRs.
test('the quarantine list claims the fullstack lanes and no rust crate', () => {
    const targets = computeTargets(['.test_quarantine.json'], CONTEXT)
    assert.equal(targets.includes('py:core'), true)
    assert.equal(targets.includes('fe:core'), true)
    assert.equal(
        targets.some((target) => target.startsWith('rust:crate:')),
        false
    )
    assert.notDeepEqual(targets, EVERYTHING)
})

// paths-filter decides which jobs run inside a single run's own diff, so no
// run's outcome depends on it jointly with another queue entry. Its own CI and
// its .depot shadow share the lane.
test('the paths-filter action and its CI share the ci-tooling lane', () => {
    for (const file of [
        '.github/actions/paths-filter/src/filter.ts',
        '.github/actions/paths-filter/dist/index.js',
        '.github/workflows/ci-paths-filter.yml',
        '.depot/actions/paths-filter/src/filter.ts',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['ci-tooling'], file)
    }
})

// pnpm patches resolve inside the JS workspace the way pnpm-lock.yaml does,
// and depot.json is billing and cache routing that fails its own PR's builds
// alone.
test('pnpm patches take the JS lanes and depot.json the repo-config lane', () => {
    assert.deepEqual(computeTargets(['patches/dayjs@1.11.11.patch'], CONTEXT), computeTargets(['.oxlintrc.json'], CONTEXT))
    assert.deepEqual(computeTargets(['depot.json'], CONTEXT), ['repo-config'])
})

// The schema-impact pair feeds turbo-discover's backend product selection, the
// same radius the snob selector holds.
test('the schema selection scripts claim the python lanes', () => {
    for (const file of ['.github/scripts/schema-impact.js', '.github/scripts/schema_usage_scan.py']) {
        assert.deepEqual(computeTargets([file], CONTEXT), computeTargets(['mypy.ini'], CONTEXT), file)
    }
})

// Called by the rust smoke build and the rust image CD; the image map is also
// parsed by rust-compute-affected in the rust and nodejs PR checks.
test('the rust image builder and image map span rust plus deploy', () => {
    for (const file of ['.github/workflows/_rust-build-images.yml', '.github/rust-images.yml']) {
        const targets = computeTargets([file], CONTEXT)
        assert.equal(targets.includes('deploy'), true, file)
        assert.equal(
            targets.some((target) => target.startsWith('rust:crate:')),
            true,
            file
        )
        assert.equal(targets.includes('fe:core'), false, file)
        assert.equal(targets.includes('py:core'), false, file)
    }
})

// cargo-dist packages the CLI, which ci-cli.yml builds from services/mcp
// sources, so the manifest belongs in the same lane as both.
test('the cargo-dist manifest shares the cli lane', () => {
    assert.deepEqual(computeTargets(['dist-workspace.toml'], CONTEXT), computeTargets(['cli/src/main.rs'], CONTEXT))
})

test('a single-language workflow claims that language rather than everything', () => {
    assert.deepEqual(
        computeTargets(['.github/workflows/ci-frontend.yml'], CONTEXT),
        computeTargets(['.oxlintrc.json'], CONTEXT)
    )
    for (const file of [
        '.github/workflows/ci-backend.yml',
        '.github/workflows/ci-python.yml',
        '.github/workflows/ci-clickhouse-multinode-migrations.yml',
        // The backend test-timing pair and the IDOR coverage check run only in
        // ci-backend and its timing workflow.
        '.github/scripts/optimize_test_durations.py',
        '.github/scripts/test_optimize_test_durations.py',
        '.github/scripts/check-idor-model-coverage.py',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), computeTargets(['mypy.ini'], CONTEXT), file)
    }
})

// Suites that run the backend and the frontend together used to widen to every
// lane, which serialized them against rust and the standalone trees no E2E or
// image build can touch.
test('a full-stack suite claims both language families and no rust crate', () => {
    for (const file of [
        '.github/workflows/ci-e2e-playwright.yml',
        '.github/workflows/ci-hog.yml',
        '.github/workflows/container-images-ci.yml',
        '.github/workflows/cd-sandbox-base-image.yml',
        '.github/workflows/ci-recording-rasterizer-container.yml',
        '.github/scripts/report_test_timings.py',
        'Dockerfile.playwright',
        'Dockerfile.sandbox',
    ]) {
        const targets = computeTargets([file], CONTEXT)
        for (const target of ['py:core', 'py:product:alpha', 'fe:core', 'node:ingestion', 'svc:mcp']) {
            assert.equal(targets.includes(target), true, `${target} (from ${file})`)
        }
        assert.equal(
            targets.some((target) => target.startsWith('rust:crate:')),
            false,
            file
        )
        assert.notDeepEqual(targets, EVERYTHING, file)
    }
})

// No required pull-request or merge-queue check runs a release or CD workflow,
// so no queue combination tests it either way and one shared lane is the
// honest radius.
test('release and CD workflows share the deploy lane', () => {
    for (const file of [
        '.github/workflows/container-images-cd.yml',
        '.github/workflows/cd-mcp-image.yml',
        '.github/workflows/rust-docker-build.yml',
        '.github/workflows/release-cli.yml',
        '.github/workflows/publish-hogli.yml',
        'Dockerfile.llm-analytics',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['deploy'], file)
    }
})

// The hobby smoke test is the only suite that reads the install scripts, so
// the scripts and the two workflows that run them have to share one lane: a
// script change and the workflow change that runs it must not merge in
// parallel.
test('the hobby scripts and their smoke test share one lane', () => {
    for (const file of [
        '.github/workflows/ci-hobby.yml',
        '.github/workflows/ci-hobby-installer.yml',
        'bin/hobby-installer/go.mod',
        'bin/hobby-ci.py',
        'bin/deploy-hobby',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['hobby'], file)
    }
    // A bin file read across language families keeps the old radius.
    assert.deepEqual(computeTargets(['bin/download-mmdb'], CONTEXT), EVERYTHING)
})

// The bot, report, and sync workflows gate no required check, so a break costs
// a bot action rather than a merge. Each one shares the lane with the script
// and config it runs, which is the pair that has to stay serialized.
test('automation workflows share one lane with their scripts and config', () => {
    for (const file of [
        '.github/workflows/auto-assign-reviewers.yml',
        '.github/scripts/assign-reviewers.js',
        '.github/workflows/weekly-flaky-report.yml',
        '.github/scripts/weekly-flaky-report.mjs',
        '.github/scripts/weekly-report-common.mjs',
        '.github/auto-assign-labels.json',
        '.github/renovate.json5',
        '.github/workflows/stale.yaml',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['repo-automation'], file)
    }
})

// The dev stack is exercised only by the dev-setup check and the sandbox
// selftests, so its process lists, launchers, and helpers share one lane with
// those workflows instead of serializing the whole queue.
test('the dev stack and its selftests share the dev-env lane', () => {
    for (const file of [
        '.github/workflows/ci-dev-setup.yml',
        '.github/workflows/dev-sandbox-selftest.yml',
        'bin/mprocs.yaml',
        'bin/start',
        'bin/start-rust-service',
        'bin/dev-sandbox',
        'bin/check_hosts',
        'bin/docker-dev',
        'bin/helpers/_utils.sh',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['dev-env'], file)
    }
})

// The unified app image backs E2E, hobby, and production, so its baked-in
// entrypoints claim all three radii and stay clear of the rust crates.
test('app-image entrypoints claim the fullstack, hobby, and deploy lanes', () => {
    for (const file of [
        'bin/docker-server',
        'bin/migrate',
        'bin/celery-queues.env',
        'bin/start-backend',
        'Dockerfile',
        'Dockerfile.node',
        '.dockerignore',
    ]) {
        const targets = computeTargets([file], CONTEXT)
        for (const target of ['py:core', 'fe:core', 'node:ingestion', 'hobby', 'deploy']) {
            assert.equal(targets.includes(target), true, `${target} (from ${file})`)
        }
        assert.equal(
            targets.some((target) => target.startsWith('rust:crate:')),
            false,
            file
        )
    }
})

// A docs-check change has to overlap the docs PRs it can break against, which
// claim the prose lane.
test('docs suites and their scripts claim the prose lane', () => {
    for (const file of ['.github/workflows/docs-preview-trigger.yml', '.github/scripts/check-docs-links.js']) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['prose'], file)
    }
    // The survey check compares docs against frontend sources, so it spans
    // both.
    const survey = computeTargets(['.github/workflows/ci-survey-sdk-check.yml'], CONTEXT)
    assert.equal(survey.includes('prose'), true)
    assert.equal(survey.includes('fe:core'), true)
    assert.equal(survey.includes('py:core'), false)
})

// A rule may list several domains for a file read on both sides of a split;
// the file claims every listed domain's lanes.
test('a multi-domain rule claims the union of its domains', () => {
    const deltalite = computeTargets(['.github/workflows/ci-deltalite-python.yml'], CONTEXT)
    assert.equal(deltalite.includes('py:core'), true)
    assert.equal(
        deltalite.some((target) => target.startsWith('rust:crate:')),
        true
    )
    assert.equal(deltalite.includes('fe:core'), false)
    // The separation gate path-filters Django, sqlx, and nodejs migrations, so
    // it spans all three families and matches what the same change spelled as
    // files would claim.
    assert.deepEqual(
        computeTargets(['.github/workflows/ci-migrations-service-separation-check.yml'], CONTEXT),
        computeTargets(['mypy.ini', 'rust/Cargo.toml', 'nodejs/src/index.ts'], CONTEXT)
    )
})

// The schema codegen pipeline turns schema.json into the generated artifacts
// both families read, which is the product-surface radius.
test('the schema codegen scripts claim the product-surface lanes', () => {
    assert.deepEqual(
        computeTargets(['bin/build-schema-python.sh'], CONTEXT),
        computeTargets(['frontend/src/products.json'], CONTEXT)
    )
})

// A Depot shadow is kept apples-to-apples with its canonical by the
// shadow-drift check and posts non-blocking statuses, so it can only affect
// what the canonical affects. The narrowing direction is the guard: a shadow
// of something no rule has placed must stay on the .github blanket rather
// than fall through unclaimed.
test('a depot shadow resolves through its canonical workflow rules', () => {
    assert.deepEqual(
        computeTargets(['.depot/workflows/ci-backend.yml'], CONTEXT),
        computeTargets(['.github/workflows/ci-backend.yml'], CONTEXT)
    )
    assert.deepEqual(
        computeTargets(['.depot/workflows/ci-backend-update-test-timing.yml'], CONTEXT),
        computeTargets(['mypy.ini'], CONTEXT)
    )
    assert.deepEqual(computeTargets(['.depot/actions/pnpm-install/action.yml'], CONTEXT), EVERYTHING)
    assert.deepEqual(computeTargets(['.depot/workflows/some-new-shadow.yml'], CONTEXT), EVERYTHING)
    // Shadow markdown is prose like any other.
    assert.deepEqual(computeTargets(['.depot/actions/paths-filter/README.md'], CONTEXT), ['prose'])
})

// The guard is the narrowing direction: a service workflow whose directory is
// gone must widen rather than claim a lane no other PR can reach.
test('a service suite workflow claims its service lane and widens without it', () => {
    assert.deepEqual(computeTargets(['.github/workflows/ci-oauth-proxy.yml'], CONTEXT), ['svc:oauth-proxy'])
    assert.deepEqual(computeTargets(['.github/workflows/ci-llm-gateway.yml'], CONTEXT), EVERYTHING)
})

test('desktop workflows claim the desktop product lanes and widen without the product', () => {
    const withDesktop = { ...CONTEXT, products: [...CONTEXT.products, 'desktop'] }
    for (const file of ['.github/workflows/desktop-ci.yml', '.github/workflows/desktop-release.yml']) {
        assert.deepEqual(computeTargets([file], withDesktop), ['fe:product:desktop', 'py:product:desktop'], file)
    }
    assert.deepEqual(computeTargets(['.github/workflows/desktop-ci.yml'], CONTEXT), EVERYTHING)
})

// The Proto CI workflow gates buf lint and the stub drift checks over every
// tree, which is the same radius the root buf configuration gets.
test('the proto workflow claims every proto tree rather than everything', () => {
    assert.deepEqual(
        computeTargets(['.github/workflows/ci-proto.yml'], PROTO_CONTEXT),
        computeTargets(['proto/buf.yaml'], PROTO_CONTEXT)
    )
})

test('the cli workflow and the reusable release plan share the cli lane', () => {
    for (const file of ['.github/workflows/ci-cli.yml', '.github/workflows/release.yml']) {
        assert.deepEqual(computeTargets([file], CONTEXT), computeTargets(['cli/src/main.rs'], CONTEXT), file)
    }
})

test('the hogbox preview workflows keep the hogbox tooling lane', () => {
    for (const file of ['.github/workflows/hogbox-preview-env.yml', '.github/workflows/hogbox-preview-cleanup.yml']) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['tools:hogbox-preview'], file)
    }
})

test('the mcp ui-apps workflow claims the product-surface readers', () => {
    assert.deepEqual(
        computeTargets(['.github/workflows/ci-mcp-ui-apps.yml'], CONTEXT),
        computeTargets(['frontend/src/products.json'], CONTEXT)
    )
})

// The skills build renders templates that import product Python, and the
// embedded-payload job regenerates products/*/frontend/generated/, so the
// workflow spans both language families. Its paths filter never matches
// .agents/, so that lane stays out.
test('the agent-skills workflow claims both language families', () => {
    const targets = computeTargets(['.github/workflows/ci-agent-skills.yml'], CONTEXT)
    assert.equal(targets.includes('agents'), false)
    assert.equal(targets.includes('py:core'), true)
    assert.equal(targets.includes('fe:core'), true)
    assert.deepEqual(targets, computeTargets(['mypy.ini', '.oxlintrc.json'], CONTEXT))
})

test('the ml-mirror sidecar image and its workflow stay on the node lane', () => {
    for (const file of ['.github/workflows/ci-ml-mirror-image-scrub-container.yml', 'Dockerfile.ml-mirror-image-scrub']) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['node:ingestion'], file)
    }
})

// Semgrep enforces the languages: declaration on every rule, so it is a sound
// source for the radius. The IDOR allowlist every new team-scoped model has to
// touch is a python rule, and used to serialize those PRs against the frontend.
test('a semgrep rule claims the lanes of the languages it declares', () => {
    assert.deepEqual(
        computeTargets(['.semgrep/rules/security/py-rule.yaml'], CONTEXT),
        computeTargets(['mypy.ini'], CONTEXT)
    )
    assert.deepEqual(
        computeTargets(['.semgrep/rules/devex/ts-rule.yaml'], CONTEXT),
        computeTargets(['.oxlintrc.json'], CONTEXT)
    )
    // A rule spanning languages with no single lane mapping, and a rule file
    // the context never resolved, both keep the old radius.
    assert.deepEqual(computeTargets(['.semgrep/rules/devex/generic-rule.yaml'], CONTEXT), EVERYTHING)
    assert.deepEqual(computeTargets(['.semgrep/rules/devex/unknown-rule.yaml'], CONTEXT), EVERYTHING)
})

test('semgrep language declarations resolve to a single domain or widen', () => {
    assert.deepEqual([...parseSemgrepLanguages('      languages: [python]')], ['python'])
    assert.deepEqual([...parseSemgrepLanguages('  languages: [typescript, javascript]')], ['typescript', 'javascript'])
    assert.deepEqual([...parseSemgrepLanguages('languages:\n    - python\n    - py\n')], ['python', 'py'])
    assert.equal(semgrepDomain('languages: [python]\nlanguages: [py]'), PYTHON)
    assert.equal(semgrepDomain('languages: [typescript, javascript]'), JAVASCRIPT)
    // Both sides of the split, an unmapped language, and no declaration at all.
    assert.equal(semgrepDomain('languages: [python]\nlanguages: [typescript]'), UNIVERSAL)
    assert.equal(semgrepDomain('languages: [generic]'), UNIVERSAL)
    assert.equal(semgrepDomain('rules:\n  - id: x\n'), UNIVERSAL)
})

// Markdown in a tripwire tree compiles into nothing and no suite reads it. A
// pull request template used to serialize a PR against the entire repo.
test('markdown inside a tripwire tree is prose, not a CI change', () => {
    for (const file of ['.github/pull_request_template.md', '.semgrep/rules/devex/README.md']) {
        assert.equal(isTripwire(file), false, file)
        assert.deepEqual(computeTargets([file], CONTEXT), ['prose'], file)
    }
})

test('the widest tripwire in a change set wins', () => {
    // A language-scoped tripwire accumulates alongside the narrow files rather
    // than replacing them, so the product's own lane survives.
    const scoped = computeTargets(['products/alpha/backend/api.py', 'mypy.ini'], CONTEXT)
    assert.equal(scoped.includes('py:product:alpha'), true)
    assert.equal(scoped.includes('fe:core'), false)
    // A universal one still swallows everything.
    assert.deepEqual(computeTargets(['products/alpha/backend/api.py', 'hogli.yaml'], CONTEXT), EVERYTHING)
})

// The single most dangerous failure mode: an unclaimed path yielding an empty
// target set reads to Trunk as "overlaps nothing", so the PR merges in parallel
// with everything. A new top-level directory must widen, never narrow.
test('an unmapped path widens rather than yielding an empty target set', () => {
    for (const file of [
        'some-new-toplevel/thing.go',
        'common/unrecognized/x.ts',
        // agent-os/ and share/ hold nothing but markdown today, so a file that
        // is not prose there is as unclassified as a brand new tree.
        'share/geoip.py',
        'agent-os/generate.py',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), EVERYTHING, `${file} should widen`)
    }
})

// THE INVARIANT behind replacing the sentinel: a widened PR is only equivalent
// to "ALL" if the enumerated set contains every target any other PR can claim.
// One missing target makes the widened PR disjoint from the PR claiming it,
// which is exactly the silent break the sentinel existed to prevent.
test('every target the rules can emit appears in the enumerated universe', () => {
    const everyRule = [
        'posthog/models/team.py',
        'ee/settings.py',
        'ee/frontend/x.tsx',
        'frontend/src/index.tsx',
        'packages/quill/src/index.ts',
        'playwright/spec.ts',
        'nodejs/src/main.ts',
        'services/mcp/src/index.ts',
        'services/oauth-proxy/src/index.ts',
        'docs/onboarding/index.ts',
        '.agents/skills/merging-prs/SKILL.md',
        'cli/src/main.rs',
        'livestream/auth/jwt.go',
        'funnel-udf/src/codec.rs',
        'terraform/us/dashboards.tf',
        '.stamphog/policy.yml',
        '.vscode/launch.json',
        'tools/phrocs/src/main.rs',
        'products/stamphog/packages/pr-approval-agent/policy.py',
        'common/hogvm/x.py',
        'common/storybook/x.ts',
        'common/__init__.py',
        'common/fixtures/ai-multimodal/screenshot.png',
        'rust/shared/src/lib.rs',
        'rust/Dockerfile',
        'rust/persons_migrations/x.sql',
        'rust/cyclotron-node-migrations/x.sql',
        'rust/bin/migrate-persons',
        'products/alpha/backend/api.py',
        'products/beta/frontend/Scene.tsx',
        'products/db_routing.yaml',
        'dist-workspace.toml',
        'LICENSE',
        'manage.py',
        'posthog.json',
        'README.md',
        '.oxlintrc.json',
        'mypy.ini',
        '.github/workflows/ci-rust.yml',
        '.github/workflows/ci-e2e-playwright.yml',
        '.github/workflows/container-images-cd.yml',
        '.github/workflows/ci-hobby.yml',
        '.github/workflows/ci-oauth-proxy.yml',
        '.github/workflows/ci-agent-skills.yml',
        '.github/workflows/hogbox-preview-env.yml',
        '.github/workflows/ci-cli.yml',
        'bin/hobby-ci.py',
        'Dockerfile.llm-analytics',
        '.github/workflows/stale.yaml',
        '.github/workflows/ci-dev-setup.yml',
        '.github/workflows/ci-deltalite-python.yml',
        '.github/workflows/docs-preview-trigger.yml',
        '.github/workflows/terragrunt-posthog.yaml',
        '.github/workflows/ci-livestream.yml',
        '.github/scripts/check-agents-md-symlinks.sh',
        '.github/ISSUE_TEMPLATE/bug_report.yml',
        'bin/docker-server',
        'bin/mprocs.yaml',
        'bin/build-schema-python.sh',
        'bin/update-bots-list',
        '.depot/workflows/ci-backend.yml',
        'tools/snob_backend_test_selection_shadow.py',
        'tools/playwright_area_map.json',
        '.prettierignore',
        '.trunk/trunk.yaml',
        'owners.yaml',
        '.github/CODEOWNERS',
        '.test_quarantine.json',
        '.github/actions/paths-filter/src/filter.ts',
        'Dockerfile',
        '.dockerignore',
        'patches/dayjs@1.11.11.patch',
        'depot.json',
        '.github/workflows/_rust-build-images.yml',
    ]
    for (const file of everyRule) {
        const targets = computeTargets([file], CONTEXT)
        assert.notEqual(targets, ALL, `${file} should enumerate`)
        for (const target of targets) {
            assert.equal(EVERYTHING.includes(target), true, `${target} (from ${file}) is missing from allKnownTargets`)
        }
    }
})

// Enumeration is only safe when it is complete, so a context that cannot name
// every crate or service has to fall back to the sentinel rather than upload a
// set that is missing lanes.
test('an incomplete context falls back to the ALL sentinel', () => {
    assert.equal(allKnownTargets({ ...CONTEXT, rustInventory: null }), null)
    assert.equal(allKnownTargets({ ...CONTEXT, services: null }), null)
    assert.equal(computeTargets(['some-new-toplevel/thing.go'], { ...CONTEXT, services: null }), ALL)
})

test('tripwire domains are reported for telemetry', () => {
    assert.equal(tripwireDomain('hogli.yaml'), UNIVERSAL)
    assert.equal(tripwireDomain('.oxlintrc.json'), JAVASCRIPT)
    assert.equal(tripwireDomain('mypy.ini'), PYTHON)
    assert.equal(tripwireDomain('.github/workflows/ci-rust.yml'), RUST)
    assert.equal(tripwireDomain('.github/pull_request_template.md'), null)
    assert.equal(tripwireDomain('products/alpha/backend/api.py'), null)
})

// Each of these went to ALL only because no rule named the directory, which
// serialized the PR against the whole repo for a change no suite outside its
// own tree can see.
test('standalone top-level trees hold a lane instead of widening', () => {
    assert.deepEqual(computeTargets(['terraform/us/project-2/dashboards.tf'], CONTEXT), ['terraform'])
    assert.deepEqual(computeTargets(['livestream/auth/jwt.go'], CONTEXT), ['livestream'])
    assert.deepEqual(computeTargets(['funnel-udf/src/codec.rs'], CONTEXT), ['funnel-udf'])
})

// funnel-udf and cli are cargo workspaces of their own, outside rust/ and
// outside its lockfile, so the crate graph must not be consulted for them.
test('standalone cargo workspaces stay out of the rust crate lanes', () => {
    const udf = computeTargets(['funnel-udf/src/codec.rs'], CONTEXT)
    const rust = computeTargets(['rust/shared/src/lib.rs'], CONTEXT)
    assert.deepEqual(
        udf.filter((target) => rust.includes(target)),
        []
    )
})

// ci-cli.yml builds the CLI from services/mcp sources, so a lane of its own
// would let an mcp change and the cli change that consumes it merge in
// parallel.
test('cli changes share a lane with the mcp service', () => {
    const cli = computeTargets(['cli/src/main.rs'], CONTEXT)
    const mcp = computeTargets(['services/mcp/src/index.ts'], CONTEXT)
    assert.deepEqual(cli, ['cli', 'svc:mcp'])
    assert.equal(
        cli.some((target) => mcp.includes(target)),
        true
    )
})

// The pr-approval-agent suite reads both, and the policy files are markdown
// that the prose rule would otherwise treat as inert.
test('stamphog policy files claim the suite that validates them', () => {
    assert.deepEqual(computeTargets(['.stamphog/policy.yml'], CONTEXT), ['tools:pr-approval-agent'])
    assert.deepEqual(computeTargets(['.stamphog/review-guidance.md'], CONTEXT), ['tools:pr-approval-agent'])
    // Wherever it sits, the file belongs to the suite rather than to the
    // product tree holding it.
    assert.deepEqual(computeTargets(['products/alpha/AGENT_APPROVALS.md'], CONTEXT), ['tools:pr-approval-agent'])
    assert.deepEqual(
        computeTargets(['.stamphog/policy.yml'], CONTEXT),
        computeTargets(['products/stamphog/packages/pr-approval-agent/policy.py'], CONTEXT)
    )
})

// Editor and agent configuration no suite reads. One shared lane is enough:
// these PRs are rare, and the alternative is a lane per tree for files that
// cannot change any test's outcome.
test('editor and agent configuration shares one lane', () => {
    for (const file of [
        '.vscode/launch.json',
        '.zed/debug.json',
        '.husky/pre-commit',
        '.claude/settings.json',
        '.greptile/config.json',
        '.trunk/trunk.yaml',
        '.trunk/.gitignore',
        // The same class of file, one per root path rather than one per tree.
        '.cursorignore',
        '.editorconfig',
        '.gitattributes',
        '.gitignore',
        '.mcp.json',
        '.watchmanconfig',
        '.worktreeinclude',
        'LICENSE',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['repo-config'], file)
    }
    // Markdown in those trees is still prose, so a PR that only reorganizes an
    // agent doc claims no lane at all.
    assert.deepEqual(computeTargets(['.claude/agents/code-reviewer.md'], CONTEXT), ['prose'])
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

// The determinator's answer is the affected set (the changed crates plus
// their dependents), so it is used as it stands rather than closed over again.
// The script holds no crate dependency edges of its own.
test('a rust change takes its crate set from the determinator answer', () => {
    assert.deepEqual(
        computeTargets(['rust/shared/src/lib.rs'], { ...CONTEXT, rustAffectedCrates: ['consumer', 'shared'] }),
        ['rust:crate:consumer', 'rust:crate:shared']
    )
    assert.deepEqual(
        computeTargets(['rust/unrelated/src/main.rs'], { ...CONTEXT, rustAffectedCrates: ['unrelated'] }),
        ['rust:crate:unrelated']
    )
})

// Without the answer the script cannot name the dependents of the changed
// crate, and a set missing a dependent is the direction that breaks master.
test('a rust change without a determinator answer claims every crate', () => {
    assert.deepEqual(computeTargets(['rust/shared/src/lib.rs'], CONTEXT), [
        'rust:crate:consumer',
        'rust:crate:shared',
        'rust:crate:unrelated',
    ])
})

// An answer that omits a crate the changed paths sit in means the determinator
// and this script disagree about the workspace, and a lane list built from
// half of that disagreement could be the narrow half.
test('an answer that omits a seeded crate widens to every crate', () => {
    assert.deepEqual(computeTargets(['rust/consumer/src/main.rs'], { ...CONTEXT, rustAffectedCrates: ['shared'] }), [
        'rust:crate:consumer',
        'rust:crate:shared',
        'rust:crate:unrelated',
    ])
})

test('an unresolvable rust crate inventory reports every crate instead of narrowing', () => {
    const noInventory = { ...CONTEXT, rustInventory: null }
    assert.equal(computeTargets(['rust/shared/src/lib.rs'], noInventory), ALL)
})

test('a rust path outside every known crate widens', () => {
    assert.deepEqual(computeTargets(['rust/not-a-crate/file.rs'], CONTEXT), EVERYTHING)
})

// A binding crate compiles into a native module the JS workspace imports, so
// the lane cannot stop at rust/. A PR changing the binding and a PR changing
// its caller in nodejs/ must not come out disjoint.
test('a crate that builds an npm package claims the lanes importing it', () => {
    const bindingContext = {
        ...CONTEXT,
        rustInventory: { ...CONTEXT.rustInventory, nativeBindings: new Set(['consumer']) },
    }
    // Reached through the answer's closure rather than directly: `shared` is
    // not itself a binding, but what it compiles into ships inside one.
    const viaDependency = computeTargets(['rust/shared/src/lib.rs'], {
        ...bindingContext,
        rustAffectedCrates: ['consumer', 'shared'],
    })
    assert.equal(viaDependency.includes('node:ingestion'), true)

    const direct = computeTargets(['rust/consumer/src/lib.rs'], {
        ...bindingContext,
        rustAffectedCrates: ['consumer'],
    })
    assert.equal(direct.includes('node:ingestion'), true)

    // A crate no binding depends on keeps its own lane.
    const unrelated = computeTargets(['rust/unrelated/src/main.rs'], {
        ...bindingContext,
        rustAffectedCrates: ['unrelated'],
    })
    assert.deepEqual(unrelated, ['rust:crate:unrelated'])

    // The every-crate fallback covers the bindings, so it reaches their
    // consumers too.
    const widened = computeTargets(['rust/shared/src/lib.rs'], bindingContext)
    assert.equal(widened.includes('node:ingestion'), true)
})

// The cargo lockfile, the manifest, and the sqlx offline data resolve nothing
// outside the cargo workspace, so the lanes they can break are the rust ones
// plus whatever reaches them through a native module, rather than every lane in
// the repo. rust/Cargo.lock is in the list on its fallback: this context carries
// no determinator answer, so it claims the same set. The narrowed case is below.
test('the cargo workspace tripwires claim the rust lanes rather than every lane', () => {
    const bindingContext = {
        ...CONTEXT,
        rustInventory: { ...CONTEXT.rustInventory, nativeBindings: new Set(['consumer']) },
    }
    for (const file of ['rust/Cargo.lock', 'rust/Cargo.toml', 'rust/.sqlx/query-0a1b.json']) {
        const targets = computeTargets([file], bindingContext)
        assert.equal(isTripwire(file), true, `${file} should still be a tripwire`)
        assert.deepEqual(
            targets.filter((target) => target.startsWith('rust:crate:')),
            ['rust:crate:consumer', 'rust:crate:shared', 'rust:crate:unrelated'],
            `${file} should claim every crate`
        )
        assert.equal(targets.includes('node:ingestion'), true, `${file} reaches the native module consumers`)
        assert.equal(targets.includes('py:core'), false, `${file} should not claim the python lanes`)
        assert.equal(targets.includes('fe:core'), false, `${file} should not claim the frontend lanes`)
    }
})

// The determinator's answer already holds the dependents of the crates the
// resolution moved, so the lockfile takes it as it stands. Without it, a
// lockfile touch claims every crate (the case above this one pins).
test('a narrowed lockfile change claims the crates the determinator named', () => {
    const targets = computeTargets(['rust/Cargo.lock'], { ...CONTEXT, rustAffectedCrates: ['consumer', 'shared'] })
    assert.deepEqual(
        targets.filter((target) => target.startsWith('rust:crate:')),
        ['rust:crate:consumer', 'rust:crate:shared']
    )
    assert.equal(targets.includes('rust:crate:unrelated'), false, 'a crate the resolution did not move keeps its lane')
})

// An answer naming no crate falls back rather than claiming nothing, because a
// lockfile-only change set would otherwise reach the empty-set guard and widen
// past the rust lanes entirely. This pins the fallback against that.
test('a determinator answer naming no crate claims every crate, not every lane', () => {
    const targets = computeTargets(['rust/Cargo.lock'], { ...CONTEXT, rustAffectedCrates: [] })
    assert.deepEqual(
        targets.filter((target) => target.startsWith('rust:crate:')),
        ['rust:crate:consumer', 'rust:crate:shared', 'rust:crate:unrelated']
    )
    assert.equal(targets.includes('py:core'), false, 'the empty-set guard should not have fired')
})

// Each of these is a way for the answer to arrive unusable, and reading one as
// "no crate" would be narrower than reality, which is the direction that breaks
// master. All of them have to read as unknown so the caller widens.
test('an unusable determinator answer reads as unknown', () => {
    for (const [name, raw] of [
        ['a skipped or failed step', ''],
        ['an unset variable', undefined],
        ['output that is not JSON', 'shared,consumer'],
        ['JSON that is not a list', '{"crates":["shared"]}'],
        ['a list holding something other than a name', '["shared", 7]'],
        ['a crate the inventory does not hold', '["shared", "ghost"]'],
    ]) {
        assert.equal(parseRustAffectedCrates(raw, CONTEXT.rustInventory), null, `${name} should read as unknown`)
    }
})

test('a determinator answer the inventory agrees with is used as it stands', () => {
    assert.deepEqual(parseRustAffectedCrates('["shared"]', CONTEXT.rustInventory), ['shared'])
})

// The determinator's workspace and this script's crate inventory are built from
// the same manifests by different code, so a name in one and not the other means
// one of them is wrong. Reads the real repo, which is the only place that can drift.
test('the crate inventory holds every crate the determinator can name', () => {
    const { rustInventory } = buildContext(REPO_ROOT)
    const members = fs
        .readFileSync(path.join(REPO_ROOT, 'rust/Cargo.toml'), 'utf8')
        .split(/^\s*\[/m)
        .find((section) => section.startsWith('workspace]'))
        .match(/members\s*=\s*\[([^\]]*)\]/)[1]
        .split(',')
        .map((entry) => entry.trim().replace(/^"|"$/g, ''))
        .filter(Boolean)
    const missing = members.filter((dir) => !rustInventory.byDir.some((crate) => crate.dir === dir))
    assert.deepEqual(missing, [], 'these workspace members are absent from the crate inventory')
})

// The consumer lanes are declared rather than derived, so a second dependent
// appearing anywhere in the pnpm workspace has to fail here. Reads the real
// workspace for that reason: a synthetic one cannot notice the new dependent.
test('nodejs is still the only workspace package importing a rust binding', () => {
    const workspaceGlobs = parseWorkspacePackageGlobs(
        fs.readFileSync(path.join(REPO_ROOT, 'pnpm-workspace.yaml'), 'utf8')
    )
    // pnpm's package globs are one level deep, so a trailing /* expands by
    // listing the directory. Negations exclude a package rather than add one.
    const expand = (glob) => {
        if (glob.startsWith('!')) {
            return []
        }
        if (!glob.endsWith('/*')) {
            return [glob]
        }
        const parent = path.join(REPO_ROOT, glob.slice(0, -2))
        if (!fs.existsSync(parent)) {
            return []
        }
        return fs
            .readdirSync(parent, { withFileTypes: true })
            .filter((entry) => entry.isDirectory())
            .map((entry) => path.posix.join(glob.slice(0, -2), entry.name))
    }
    const packageDirs = workspaceGlobs.flatMap(expand)

    // An incomplete checkout (e.g. a sparse CI checkout missing workspace
    // manifests) would silently shrink the inspection set: expand() and the
    // existsSync checks below skip whatever is absent. The git index stays
    // complete even when the working tree is sparse, so any tracked manifest
    // inside the workspace that is not on disk means the checkout dropped it.
    const matcher = compileWorkspaceMatcher(workspaceGlobs)
    const trackedManifests = execFileSync('git', ['ls-files', '-z', '--', ':(glob)**/package.json', 'package.json'], {
        cwd: REPO_ROOT,
        encoding: 'utf8',
    })
        .split('\0')
        .filter(Boolean)
    assert.ok(trackedManifests.length > 0, 'git ls-files found no manifests, so the checkout check below is vacuous')
    for (const manifest of new Set(trackedManifests)) {
        if (manifest !== 'package.json' && !matcher(manifest)) {
            continue
        }
        assert.ok(
            fs.existsSync(path.join(REPO_ROOT, manifest)),
            `${manifest} is tracked by git but absent on disk — an incomplete checkout guts this guard`
        )
    }

    const bindingPackages = new Set()
    for (const dir of packageDirs) {
        if (!dir.startsWith('rust/')) {
            continue
        }
        const manifest = path.join(REPO_ROOT, dir, 'package.json')
        if (fs.existsSync(manifest)) {
            bindingPackages.add(JSON.parse(fs.readFileSync(manifest, 'utf8')).name)
        }
    }
    assert.ok(bindingPackages.size > 0, 'expected the rust workspace to publish npm packages')

    const dependentDirs = []
    for (const dir of packageDirs) {
        if (dir.startsWith('rust/')) {
            continue
        }
        const manifest = path.join(REPO_ROOT, dir, 'package.json')
        if (!fs.existsSync(manifest)) {
            continue
        }
        const pkg = JSON.parse(fs.readFileSync(manifest, 'utf8'))
        const deps = { ...pkg.dependencies, ...pkg.devDependencies, ...pkg.optionalDependencies }
        if (Object.keys(deps).some((name) => bindingPackages.has(name))) {
            dependentDirs.push(dir)
        }
    }
    assert.deepEqual(
        dependentDirs.sort(),
        ['nodejs'],
        `NATIVE_BINDING_CONSUMER_LANES (${NATIVE_BINDING_CONSUMER_LANES.join(', ')}) must cover every dependent`
    )
})

// The cargo lockfile claims no python lane, which holds only while every python
// package resolves from a registry. The workspace does contain two pyo3 crates,
// and the python suites install them as released wheels pinned by version, so a
// cargo resolution change cannot reach a python lane without a pyproject.toml
// and uv.lock bump that is universal anyway. Switching either to a local build
// would break that, and it would break it silently, so it has to fail here.
test('no python package is built from a path inside the cargo workspace', () => {
    const lock = fs.readFileSync(path.join(REPO_ROOT, 'uv.lock'), 'utf8')
    const localSources = [...lock.matchAll(/source = \{ (?:editable|directory|path|virtual) = "([^"]+)"/g)].map(
        (match) => match[1]
    )
    assert.notEqual(localSources.length, 0, 'uv.lock parse produced nothing, so the assertion below is vacuous')
    assert.deepEqual(
        localSources.filter((source) => source.startsWith('rust/')),
        [],
        'a python package built from rust/ needs its lanes added to the rust/Cargo.lock tripwire'
    )
})

// The crate lanes are the ceiling for anything configuring the workspace as a
// whole, and a file sitting at rust/ is that by construction: the Dockerfiles
// its images build from, the compose stack, the dotfiles, the license.
test('workspace-level rust files claim the crates rather than everything', () => {
    const crates = ['rust:crate:consumer', 'rust:crate:shared', 'rust:crate:unrelated']
    for (const file of [
        'rust/Dockerfile',
        'rust/docker-compose.yml',
        'rust/depot.json',
        'rust/owners.yaml',
        'rust/LICENSE',
        'rust/.env',
        'rust/.cargo/config.toml',
        'rust/.config/nextest.toml',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), crates, file)
    }
})

// The migration sets under rust/ define schemas that suites outside Rust run
// against, so holding them to the crate lanes would put a schema change in a
// parallel lane with the code reading it.
test('rust migration sets claim the suites that read their schema', () => {
    // posthog/conftest.py replays these to build the persons database every
    // backend test runs against.
    const persons = computeTargets(['rust/persons_migrations/20260206000001_add_last_seen_at.sql'], CONTEXT)
    assert.equal(persons.includes('py:core'), true)
    assert.equal(persons.includes('py:product:alpha'), true)
    assert.equal(persons.includes('rust:crate:shared'), true)
    assert.equal(persons.includes('fe:core'), false)
    assert.notDeepEqual(persons, EVERYTHING)

    // The cyclotron tables the nodejs CDP consumers read and write, and nothing
    // in the frontend, so the nodejs lane rides along on its own.
    const cyclotron = computeTargets(['rust/cyclotron-node-migrations/20260303000001_initial.sql'], CONTEXT)
    assert.equal(cyclotron.includes('node:ingestion'), true)
    assert.equal(cyclotron.includes('rust:crate:shared'), true)
    assert.equal(cyclotron.includes('fe:core'), false)
    assert.equal(cyclotron.includes('py:core'), false)

    // The migrate entrypoints apply every set, so they take the union.
    const entrypoint = computeTargets(['rust/bin/migrate-persons'], CONTEXT)
    assert.equal(entrypoint.includes('py:core'), true)
    assert.equal(entrypoint.includes('node:ingestion'), true)
    assert.equal(entrypoint.includes('rust:crate:shared'), true)

    // A set nothing outside Rust reads stays inside the crate lanes.
    assert.deepEqual(computeTargets(['rust/behavioral_cohorts_migrations/x.sql'], CONTEXT), [
        'rust:crate:consumer',
        'rust:crate:shared',
        'rust:crate:unrelated',
    ])
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

const withContractSurface = (product, inputs) => ({
    ...CONTEXT,
    contractSurfaces: new Map([[product, compileContractMatcher(inputs)]]),
})

// Nothing outside the product can import a file the product never exposes, so
// no other PR can add a call to it and there is no combination to serialize.
test('a change outside a declared contract surface keeps its own lane', () => {
    const context = withContractSurface('alpha', ['backend/facade/**'])
    assert.deepEqual(computeTargets(['products/alpha/backend/connectors/mongo.py'], context), ['py:product:alpha'])
})

test('a change inside a declared contract surface still cascades to dependents', () => {
    const context = withContractSurface('alpha', ['backend/facade/**'])
    assert.deepEqual(computeTargets(['products/alpha/backend/facade/models.py'], context), [
        'py:product:alpha',
        'py:product:beta',
        'py:product:gamma',
    ])
})

// The gate applies to the change set, not to each file: a PR that touches the
// contract has to cascade no matter how much internal code sits beside it.
test('one contract file among internals still cascades', () => {
    const context = withContractSurface('alpha', ['backend/facade/**'])
    const targets = computeTargets(
        ['products/alpha/backend/connectors/mongo.py', 'products/alpha/backend/facade/models.py'],
        context
    )
    assert.equal(targets.includes('py:product:gamma'), true)
})

// The absence of a declaration has to mean "all of it is contract". Reading it
// as "none of it" would hand every isolated product a lane it has not earned.
test('a product that declares no contract surface cascades on any backend file', () => {
    const targets = computeTargets(['products/alpha/backend/connectors/mongo.py'], CONTEXT)
    assert.equal(targets.includes('py:product:gamma'), true)
})

// Both declarations are read from the PR's own tree, so a change that narrows
// the contract and edits a file it just removed would otherwise be gated
// against the narrower version and never reach its dependents.
test('editing the declarations that define the gate always cascades', () => {
    const context = withContractSurface('alpha', ['backend/facade/**'])
    for (const file of ['products/alpha/turbo.json', 'products/alpha/package.json']) {
        const targets = computeTargets([file], context)
        assert.equal(targets.includes('py:product:gamma'), true, file)
    }
})

// Isolation is the claim that a product's change can be tested alone, and the
// contract-check script alone does not back it: without a turbo.json the task
// keeps the root inputs, which are the product's whole backend. turbo-discover
// reads the same pair, so a reader that accepted the script alone would call a
// product isolated in one place and not the other.
test('isolation needs both the contract-check script and a narrowed turbo.json', () => {
    const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'isolation-'))
    const write = (product, files) => {
        fs.mkdirSync(path.join(repoRoot, 'products', product), { recursive: true })
        for (const [name, body] of Object.entries(files)) {
            fs.writeFileSync(path.join(repoRoot, 'products', product, name), JSON.stringify(body))
        }
    }
    const contractScript = { scripts: { 'backend:contract-check': 'true' } }
    const narrowed = { tasks: { 'backend:contract-check': { inputs: ['backend/facade/**'] } } }
    write('declared', { 'package.json': contractScript, 'turbo.json': narrowed })
    write('script-only', { 'package.json': contractScript })
    write('inputs-only', { 'turbo.json': narrowed })
    write('neither', { 'package.json': {} })

    const products = ['declared', 'inputs-only', 'neither', 'script-only']
    const isolated = listIsolatedProducts(repoRoot, products, loadContractSurfaces(repoRoot, products))

    assert.deepEqual([...isolated], ['declared'])
})

test('contract inputs honor negation and drop inputs outside the product', () => {
    const matcher = compileContractMatcher(['backend/**/*.py', '!backend/**/__pycache__/**', '../../uv.lock'])
    assert.equal(matcher('backend/api.py'), true)
    assert.equal(matcher('backend/facade/models.py'), true)
    assert.equal(matcher('backend/__pycache__/api.py'), false)
    assert.equal(matcher('frontend/Scene.tsx'), false)
})

// A matcher that matched nothing would classify every file as internal, which
// is the same silent under-report as a missing cascade.
test('a contract with no product-relative inputs yields no matcher', () => {
    assert.equal(compileContractMatcher(['../../uv.lock']), null)
    assert.equal(compileContractMatcher([]), null)
})

// Only a direct importer can name the changed product's symbols. The hop beyond
// reaches the changed code through an intermediate whose own PR carries its own
// targets, and in the real graph a 31-product cycle makes the transitive
// closure the whole backend.
test('the cascade names direct importers and stops before the next hop', () => {
    const graph = new Map([
        ['beta', ['alpha']],
        ['gamma', ['beta']],
    ])
    const context = { ...CONTEXT, tachGraph: { graph, tachDependents } }
    assert.deepEqual(computeTargets(['products/alpha/backend/api.py'], context), [
        'py:product:alpha',
        'py:product:beta',
    ])
})

// The base CONTEXT keeps an empty tach graph, so no product is declared in it.
// A product `tach check` does not constrain has no bounded importer set: any
// module may import it, so its change still has to reach every backend lane.
// The tach map is read from the head tree, so a file the PR deleted has no
// importer edge left; alpha's known importers are not enough to bound its lane.
test('a deleted product python file widens to every backend target', () => {
    const file = 'products/alpha/backend/facade/api.py'
    const context = { ...TACH_DECLARED_CONTEXT, deletedFiles: new Set([file]) }
    assert.equal(computeTargets([file], context).includes('py:core'), true)
    assert.equal(computeTargets([file], TACH_DECLARED_CONTEXT).includes('py:core'), false)
})

test('a product absent from the tach graph widens to every backend target', () => {
    const targets = computeTargets(['products/gamma/backend/api.py'], CONTEXT)
    assert.equal(targets.includes('py:core'), true)
    for (const product of CONTEXT.products) {
        assert.equal(targets.includes(`py:product:${product}`), true, `expected py:product:${product}`)
    }
})

// The lane only has to answer whether another PR can reference the symbols this
// one changed, and the tach map answers exactly that. Isolation is the stronger,
// separate claim that the product's own suite is sufficient, which lets CI
// skip the full Django suite, and which products/architecture.md says tach
// cannot prove. A product can be too unsealed for that and still be bounded
// here, which is why gamma (non-isolated) narrows the same way alpha does.
test('a non-isolated product tach declares claims its own lane and its importers', () => {
    assert.deepEqual(computeTargets(['products/gamma/backend/api.py'], TACH_DECLARED_CONTEXT), [
        'py:product:beta',
        'py:product:gamma',
    ])
    // Every backend file seeds, because a product with no declared contract
    // surface has no way to say a file is internal.
    assert.deepEqual(
        computeTargets(['products/gamma/backend/internal/helper.py'], TACH_DECLARED_CONTEXT),
        computeTargets(['products/gamma/backend/api.py'], TACH_DECLARED_CONTEXT)
    )
})

// Isolation still governs the narrower question of which of a product's own
// files seed the cascade at all, which is what a contract surface declares.
test('isolation still buys a narrowed contract surface on top of the lane', () => {
    const context = {
        ...TACH_DECLARED_CONTEXT,
        isolatedProducts: new Set([...CONTEXT.isolatedProducts, 'gamma']),
        contractSurfaces: new Map([['gamma', compileContractMatcher(['backend/facade/**'])]]),
    }
    // Internals keep the product's own lane, with no cascade to beta.
    assert.deepEqual(computeTargets(['products/gamma/backend/internal/helper.py'], context), ['py:product:gamma'])
    assert.deepEqual(computeTargets(['products/gamma/backend/facade/api.py'], context), [
        'py:product:beta',
        'py:product:gamma',
    ])
})

// 63 of the products are non-isolated, and their package.json carries the
// backend:test command rather than being a bare JS manifest. It still claims a
// backend lane, just this product's own plus its importers, instead of dragging
// in every other product's.
test("a non-isolated product's declarations claim its own lane, not every backend lane", () => {
    for (const file of ['products/gamma/package.json', 'products/gamma/turbo.json']) {
        assert.deepEqual(computeTargets([file], CONTEXT), ['fe:product:gamma', 'py:product:gamma'], file)
    }
})

test("a non-isolated product's declarations still seed the dependent cascade", () => {
    const context = {
        ...CONTEXT,
        tachGraph: { graph: new Map(), tachDependents: (changed) => (changed.includes('gamma') ? ['alpha'] : []) },
    }
    assert.deepEqual(computeTargets(['products/gamma/package.json'], context), [
        'fe:product:gamma',
        'py:product:alpha',
        'py:product:gamma',
    ])
})

// Declarations narrow even for a product tach does not declare, because they
// configure only this product's own tasks. Its other files have neither a
// declared boundary nor a bounded importer set, so they still widen.
test('an undeclared product keeps widening on everything that is not a declaration', () => {
    for (const file of ['products/gamma/backend/api.py', 'products/gamma/mcp/tools.yaml']) {
        assert.equal(computeTargets([file], CONTEXT).includes('py:product:alpha'), true, file)
    }
})

test('an unavailable tach graph widens a declaration change too', () => {
    const noTach = { ...CONTEXT, tachGraph: null }
    assert.equal(computeTargets(['products/gamma/package.json'], noTach).includes('py:core'), true)
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

// ruff and pytest leave caches next to the products, and a run that treats them
// as products invents a lane per cache. Nothing downstream rejects a nonsense
// target name, so the only symptom is a local run disagreeing with CI.
test('tool caches beside the products are not products', () => {
    for (const name of ['.ruff_cache', '.pytest_cache', '__pycache__', 'node_modules']) {
        assert.equal(isProductDirectory(name), false, name)
    }
    for (const name of ['surveys', 'error_tracking', 'desktop']) {
        assert.equal(isProductDirectory(name), true, name)
    }
})

// A file at the root of products/ or common/ belongs to no single product or
// subtree, which used to send it to the full set. Both language families
// together are the honest ceiling: nothing under rust/, nodejs/, or services/
// reads any of them.
test('shared files at the root of products and common claim both language families', () => {
    const bothFamilies = [
        'py:core',
        'py:product:alpha',
        'py:product:beta',
        'py:product:gamma',
        'fe:core',
        'fe:product:alpha',
        'fe:product:beta',
        'fe:product:gamma',
    ].sort()
    for (const file of [
        'products/__init__.py',
        'products/conftest.py',
        'products/db_routing.yaml',
        'products/ruff.toml',
        'common/__init__.py',
        // Fixture data a product's Playwright spec loads and a Python recorder
        // beside it writes.
        'common/fixtures/ai-multimodal/generation-event.json',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), bothFamilies, file)
    }
    // An unrecognized subtree of common/ is still unclassified.
    assert.deepEqual(computeTargets(['common/unrecognized/x.ts'], CONTEXT), EVERYTHING)
})

test('a product file that is neither backend nor frontend claims both domains', () => {
    const targets = computeTargets(['products/beta/mcp/tools.yaml'], CONTEXT)
    assert.equal(targets.includes('py:product:beta'), true)
    assert.equal(targets.includes('fe:product:beta'), true)
})

// A product vendoring its own pnpm workspace has no backend/ + frontend/ split,
// so its manifests and configs land in the "claims both domains" case above and
// drag every backend lane along. Narrowing them is the whole point of reading
// the workspace declaration.
test('a file inside a declared workspace package claims only the product lane', () => {
    for (const file of [
        'products/gamma/packages/agent/package.json',
        'products/gamma/apps/code/snapshots.yml',
        'products/gamma/tooling/config/biome.json',
        'products/gamma/apps/code/assets/icon.svg',
    ]) {
        assert.deepEqual(computeTargets([file], WORKSPACE_CONTEXT), ['fe:product:gamma'], file)
    }
})

// The narrowing direction is the dangerous one: a backend lane that stops being
// claimed lets Trunk run this PR beside a conflicting backend PR. The workspace
// declaration says a directory holds a JS package, not that Python cannot be
// checked into it.
test('python inside a declared workspace package still claims the backend lanes', () => {
    const targets = computeTargets(['products/gamma/packages/agent/scripts/codegen.py'], WORKSPACE_CONTEXT)
    assert.equal(targets.includes('py:core'), true)
})

// Only the declared package subtrees narrow. The product root holds the files
// that decide isolation and contract surface, and anything else under the
// product is unclassified in the same way it was before.
test('files outside the declared workspace packages keep their backend claim', () => {
    // The root declarations get the narrower per-product treatment below rather
    // than the workspace one, so what matters here is that they still claim a
    // backend lane instead of being read as a JS manifest.
    assert.equal(computeTargets(['products/gamma/package.json'], WORKSPACE_CONTEXT).includes('py:product:gamma'), true)
    assert.equal(computeTargets(['products/gamma/scripts/release.mjs'], WORKSPACE_CONTEXT).includes('py:core'), true)
})

// The workspace declaration and its lockfile sit at the product root, so the
// glob matcher alone leaves them in the "claims both domains" case and a
// dependency bump in the vendored workspace still claims every backend lane.
// The second assertion is the boundary: a product with no declaration keeps
// the old widening, which a basename-only version of this rule would lose.
test('the vendored workspace files claim only the product lane', () => {
    for (const file of ['products/gamma/pnpm-workspace.yaml', 'products/gamma/pnpm-lock.yaml']) {
        assert.deepEqual(computeTargets([file], WORKSPACE_CONTEXT), ['fe:product:gamma'], file)
    }
    assert.equal(
        computeTargets(['products/alpha/pnpm-lock.yaml'], WORKSPACE_CONTEXT).includes('py:product:alpha'),
        true
    )
})

// delta stands in for products/desktop: an app imported from another
// repository that pytest.ini ignores and the tach map never walks. Its
// vendored .py files read as backend to the layout rules, so without the
// detachment check they claim every backend lane for suites that never run on
// them.
const DETACHED_CONTEXT = {
    ...WORKSPACE_CONTEXT,
    products: [...CONTEXT.products, 'delta'],
    backendDetachedProducts: new Set(['delta']),
}

test('a backend-detached product keeps its own lane instead of every backend lane', () => {
    assert.deepEqual(computeTargets(['products/delta/tools/agent/policy.py'], DETACHED_CONTEXT), ['py:product:delta'])
    assert.deepEqual(computeTargets(['products/delta/biome.json'], DETACHED_CONTEXT), [
        'fe:product:delta',
        'py:product:delta',
    ])
    // gamma is ignored by neither declaration, so the same shapes still widen.
    assert.equal(computeTargets(['products/gamma/tools/agent/policy.py'], DETACHED_CONTEXT).includes('py:core'), true)
})

// pytest.ini spells the list inside one long addopts line, so a reader anchored
// to the start of a line finds nothing and silently leaves every product
// widening.
test('pytest ignores are read from anywhere in addopts', () => {
    assert.deepEqual(
        parsePytestIgnores('addopts = -p no:warnings --ignore=tools/hogli --ignore=products/desktop --reuse-db'),
        ['tools/hogli', 'products/desktop']
    )
})

// A real pnpm-workspace.yaml carries a catalog: block right after packages:,
// and reading past the list would turn catalog entries into package globs.
test('workspace globs are read only from the packages block', () => {
    assert.deepEqual(
        parseWorkspacePackageGlobs(
            [
                'packages:',
                "  - 'apps/*'",
                '  - packages/*',
                '  - "!packages/legacy"',
                '',
                'catalog:',
                '  hono: ^1.0.0',
            ].join('\n')
        ),
        ['apps/*', 'packages/*', '!packages/legacy']
    )
})

test('a negated workspace glob excludes its subtree from the narrowing', () => {
    const matcher = compileWorkspaceMatcher(['packages/*', '!packages/legacy'])
    assert.equal(matcher('packages/agent/package.json'), true)
    assert.equal(matcher('packages/legacy/package.json'), false)
})

test('a workspace declaration with no packages block yields no matcher', () => {
    assert.equal(compileWorkspaceMatcher(parseWorkspacePackageGlobs('catalog:\n  hono: ^1.0.0\n')), null)
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

// Each selection script decides which of one suite's tests run on a PR, so an
// under-selection can only mask conflicts that suite's lanes already
// serialize. A root-level tools/ file nobody has classified still widens.
test('test-selection scripts claim the lanes of the suite they select for', () => {
    for (const file of [
        'tools/snob_backend_test_selection_shadow.py',
        'tools/test_selection_verdict.py',
        'tools/dagster_test_selection.py',
        'tools/testmon_high_fanout_files.txt',
    ]) {
        assert.deepEqual(computeTargets([file], CONTEXT), computeTargets(['mypy.ini'], CONTEXT), file)
    }
    const playwright = computeTargets(['tools/playwright_spec_selection.py'], CONTEXT)
    assert.deepEqual(playwright, computeTargets(['tools/playwright_area_map.json'], CONTEXT))
    assert.equal(playwright.includes('fe:core'), true)
    assert.equal(playwright.includes('py:core'), true)
    assert.notDeepEqual(playwright, EVERYTHING)
    assert.deepEqual(computeTargets(['tools/some_new_steering_script.py'], CONTEXT), EVERYTHING)
})

// Both are tripwires rather than falling through to the tools/ rule, which
// would give them the python product lanes and nothing else. openapi-codegen
// generates the frontend types from the backend serializers, so it claims both
// sides of the fe/py split, and owners sits on the shared ownership lane.
test('cross-domain tools are tripwires rather than backend-only', () => {
    assert.deepEqual(
        computeTargets(['tools/openapi-codegen/config.ts'], CONTEXT),
        computeTargets(['frontend/src/products.json'], CONTEXT)
    )
    assert.deepEqual(computeTargets(['tools/owners/posthog_owners/__init__.py'], CONTEXT), ['ownership'])
})

// Prose overlaps only other prose, and has to reach that lane through the
// size-0 guard rather than being widened to ALL with the unclassified paths.
test('a change set of nothing but markdown reports the prose lane', () => {
    assert.deepEqual(computeTargets(['posthog/README.md', 'docs/guide.mdx', 'CHANGELOG.md'], CONTEXT), ['prose'])
})

// The old shared docs lane serialized two PRs whose only overlap was having
// touched a markdown file, even with their code in unrelated trees. The prose
// lane must not reintroduce that by riding along with real lanes.
test('markdown alongside code contributes no lane of its own', () => {
    assert.deepEqual(
        computeTargets(['rust/unrelated/src/main.rs', 'README.md'], { ...CONTEXT, rustAffectedCrates: ['unrelated'] }),
        ['rust:crate:unrelated']
    )
})

// hogli build:skills zips products/*/skills/* (which ci-agent-skills.yml
// gates) and syncs .agents/skills/, so this markdown is a build input, not
// prose.
// Skill markdown is a build input for the Python skill build (and sometimes the product backend).
// No frontend suite reads these files, so they should claim the backend lane but not the frontend lane.
test('skill markdown keeps the lane of the tree that builds it', () => {
    assert.deepEqual(computeTargets(['.agents/skills/merging-prs/SKILL.md'], CONTEXT), ['agents'])
    const productSkill = computeTargets(['products/beta/skills/creating-experiments/SKILL.md'], CONTEXT)
    assert.equal(productSkill.includes('py:product:beta'), true)
    assert.equal(productSkill.includes('fe:product:beta'), false)
})

// The carve-out is for markdown, not for everything under skills/. A non-prose
// file there is as unclassifiable as before and keeps both halves.
test('a non-markdown skill file still claims both halves', () => {
    const script = computeTargets(['products/beta/skills/creating-experiments/scripts/run.sh'], CONTEXT)
    assert.equal(script.includes('py:product:beta'), true)
    assert.equal(script.includes('fe:product:beta'), true)
})

// docs/onboarding is the @posthog/docs-onboarding workspace package that
// frontend/package.json depends on, so its sources compile into the app. On the
// old docs lane it was disjoint from fe:core and could merge in parallel with
// the frontend PR that consumes it.
test('docs/onboarding sources claim the frontend domain', () => {
    const onboarding = computeTargets(['docs/onboarding/experiments/nextjs.tsx'], CONTEXT)
    const frontend = computeTargets(['frontend/src/lib/components/Foo.tsx'], CONTEXT)
    assert.deepEqual(onboarding, frontend)
})

// Everything under docs/ is prose today apart from that package, so a new
// non-prose tree there must widen rather than inherit the inert classification.
test('an unrecognized non-prose file under docs widens', () => {
    assert.deepEqual(computeTargets(['docs/tooling/generate.py'], CONTEXT), EVERYTHING)
})

test('independent trees stay disjoint so they can share no lane', () => {
    const rust = computeTargets(['rust/unrelated/src/main.rs'], CONTEXT)
    const node = computeTargets(['nodejs/src/worker.ts'], CONTEXT)
    const service = computeTargets(['services/mcp/src/index.ts'], CONTEXT)
    const agents = computeTargets(['.agents/skills/merging-prs/SKILL.md'], CONTEXT)
    const infra = computeTargets(['terraform/us/project-2/dashboards.tf'], CONTEXT)
    const live = computeTargets(['livestream/auth/jwt.go'], CONTEXT)
    const config = computeTargets(['.zed/debug.json'], CONTEXT)

    const sets = [rust, node, service, agents, infra, live, config]
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
