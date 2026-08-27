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
    parseCargoLockCrates,
    compileContractMatcher,
    compileWorkspaceMatcher,
    globToRegExp,
    isProductDirectory,
    isTripwire,
    listIsolatedProducts,
    loadContractSurfaces,
    parseCrateDependencies,
    parseCrateName,
    parsePytestIgnores,
    parseSemgrepLanguages,
    parseWorkspacePackageGlobs,
    reverseClosure,
    semgrepDomain,
    tripwireDomain,
    ALL,
    JAVASCRIPT,
    NATIVE_BINDING_CONSUMER_LANES,
    NODE,
    PROTO_TREES,
    PYTHON,
    REPO_ROOT,
    RUNTIME_SPAWN_EDGES,
    RUST,
    UNIVERSAL,
} = require('./trunk-impacted-targets')
const { parseTachModules, tachDependents } = require('./turbo-discover')

const CONTEXT = {
    products: ['alpha', 'beta', 'gamma'],
    services: ['mcp', 'oauth-proxy'],
    isolatedProducts: new Set(['alpha', 'beta']),
    semgrepDomains: new Map([
        ['.semgrep/rules/security/py-rule.yaml', PYTHON],
        ['.semgrep/rules/devex/ts-rule.yaml', JAVASCRIPT],
        ['.semgrep/rules/devex/generic-rule.yaml', UNIVERSAL],
    ]),
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

// What a widening decision now uploads in place of the "ALL" sentinel.
const EVERYTHING = allKnownTargets(CONTEXT)

// A graph that declares all three products, so their importer sets are bounded.
// The base CONTEXT deliberately declares none, which covers the case where a
// product sits outside `tach check` and has to keep widening.
const TACH_DECLARED_CONTEXT = {
    ...CONTEXT,
    tachGraph: {
        graph: parseTachModules(`
[[modules]]
path = "products.alpha"
depends_on = []
layer = "modules"

[[modules]]
path = "products.beta"
depends_on = ["products.gamma"]
layer = "modules"

[[modules]]
path = "products.gamma"
depends_on = []
layer = "modules"
`),
        tachDependents,
    },
}

// PROTO_TREES names the crates that compile each tree, so the crate half of
// this graph has to carry their real names. The dependent and the bystander are
// synthetic, which is what keeps the closure assertions off the real crate
// graph.
const PROTO_CONTEXT = {
    ...CONTEXT,
    rustGraph: {
        dependsOn: new Map([
            ['cymbal-proto', []],
            ['ingestion-worker-proto', []],
            ['kafka-assigner-proto', []],
            ['personhog-proto', []],
            ['personhog-consumer', ['personhog-proto']],
            ['prometheus-rw-proto', []],
            ['usage-ingestion-proto', []],
            ['unrelated', []],
        ]),
        byDir: [
            { dir: 'cymbal-proto', name: 'cymbal-proto' },
            { dir: 'ingestion-worker-proto', name: 'ingestion-worker-proto' },
            { dir: 'kafka-assigner-proto', name: 'kafka-assigner-proto' },
            { dir: 'personhog-proto', name: 'personhog-proto' },
            { dir: 'personhog-consumer', name: 'personhog-consumer' },
            { dir: 'prometheus-rw-proto', name: 'prometheus-rw-proto' },
            { dir: 'usage-ingestion-proto', name: 'usage-ingestion-proto' },
            { dir: 'unrelated', name: 'unrelated' },
        ],
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
        'bin/start',
        // Read by pytest, jest, and playwright alike, so no one domain holds it.
        '.test_quarantine.json',
        // Trees that steer what every suite runs or what it runs against: the
        // Depot copies of the composite actions, the toolchain, the service
        // configs the stack mounts, and the markdownlint config every tree's
        // prose obeys.
        '.depot/actions/paths-filter/action.yml',
        '.flox/env/manifest.toml',
        'docker/clickhouse/config.d/default.xml',
        'devenv/duckgres.yaml',
        '.config/.markdownlint-cli2.jsonc',
        // A workflow nobody has placed in a domain keeps the old radius.
        '.github/workflows/ci-e2e-playwright.yml',
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
// personhog stubs for python and nodejs. The rust half is the crate that
// compiles the tree plus the dependents the closure adds, not every crate.
test('a proto claims the consumers that generate from it rather than every lane', () => {
    const targets = computeTargets(['proto/personhog/types/v1/person.proto'], PROTO_CONTEXT)
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
    assert.deepEqual(computeTargets(['proto/cymbal/resolution/v1/resolution.proto'], PROTO_CONTEXT), [
        'rust:crate:cymbal-proto',
    ])
    assert.deepEqual(computeTargets(['proto/kafka_assigner/v1/service.proto'], PROTO_CONTEXT), [
        'rust:crate:kafka-assigner-proto',
    ])
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
        rustGraph: {
            ...PROTO_CONTEXT.rustGraph,
            dependsOn: new Map([...PROTO_CONTEXT.rustGraph.dependsOn].filter(([crate]) => crate !== 'personhog-proto')),
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
    for (const file of [
        '.env.development',
        '.env.services',
        '.envrc',
        '.dockerignore',
        'depot.json',
        'owners.yaml',
        'otel-collector-config.dev.yaml',
    ]) {
        assert.equal(tripwireDomain(file), UNIVERSAL, file)
        assert.deepEqual(computeTargets([file], CONTEXT), EVERYTHING, file)
    }
    // A product's own ownership file is not the root one and keeps its lane.
    assert.notDeepEqual(computeTargets(['products/alpha/owners.yaml'], CONTEXT), EVERYTHING)
})

// cargo-dist packages the CLI, which ci-cli.yml builds from services/mcp
// sources, so the manifest belongs in the same lane as both.
test('the cargo-dist manifest shares the cli lane', () => {
    assert.deepEqual(computeTargets(['dist-workspace.toml'], CONTEXT), computeTargets(['cli/src/main.rs'], CONTEXT))
})

test('a single-language workflow claims that language rather than everything', () => {
    const javascript = computeTargets(['.oxlintrc.json'], CONTEXT)
    for (const workflow of [
        'ci-frontend.yml',
        'ci-mcp-ui-apps.yml',
        'ci-docs-check.yml',
        'browserslist.yml',
        'publish-quill-npm.yml',
        'update-ai-costs.yml',
        'ci-playwright-container.yml',
    ]) {
        assert.deepEqual(computeTargets([`.github/workflows/${workflow}`], CONTEXT), javascript, workflow)
    }
    const python = computeTargets(['mypy.ini'], CONTEXT)
    for (const workflow of [
        'ci-backend.yml',
        'ci-python.yml',
        'ci-ai.yml',
        'ci-replay-vision-evals.yml',
        'ci-clickhouse-hcl-schema.yml',
        'ci-clickhouse-multinode-migrations.yml',
        'build-hogql-parser.yml',
        'publish-hogli.yml',
    ]) {
        assert.deepEqual(computeTargets([`.github/workflows/${workflow}`], CONTEXT), python, workflow)
    }
    const rust = computeTargets(['.github/workflows/ci-rust.yml'], CONTEXT)
    for (const workflow of [
        'rust-docker-build.yml',
        'rust-smoke-test-build.yml',
        '_rust-build-images.yml',
        'publish-replay-anonymizer-crate.yml',
        'publish-symbol-data-crate.yml',
    ]) {
        assert.deepEqual(computeTargets([`.github/workflows/${workflow}`], CONTEXT), rust, workflow)
    }
    // The workflow gating tools/openapi-codegen takes the tree's own domain.
    assert.deepEqual(
        computeTargets(['.github/workflows/ci-openapi-codegen.yml'], CONTEXT),
        computeTargets(['tools/openapi-codegen/package.json'], CONTEXT)
    )
    // Workflows serving a standalone tree take that tree's own lanes. The
    // equality against a file in the tree also guards the lane names: a
    // typo'd lane widens the workflow to everything and fails here.
    for (const [workflow, treeFile] of [
        ['ci-cli.yml', 'cli/src/main.rs'],
        ['release-cli.yml', 'cli/src/main.rs'],
        ['ci-livestream.yml', 'livestream/main.go'],
        ['ci-livestream-tui.yml', 'livestream/tui/main.go'],
        ['build-livestream-tui.yml', 'livestream/tui/main.go'],
        ['livestream-docker-image.yml', 'livestream/Dockerfile'],
        ['terragrunt-posthog.yaml', 'terraform/team-devex/main.tf'],
        ['ci-phrocs.yml', 'tools/phrocs/main.go'],
        ['build-phrocs.yml', 'tools/phrocs/Makefile'],
        ['hogbox-preview-cleanup.yml', 'tools/hogbox-preview/cli.py'],
        ['release.yml', 'cli/src/main.rs'],
    ]) {
        assert.deepEqual(
            computeTargets([`.github/workflows/${workflow}`], CONTEXT),
            computeTargets([treeFile], CONTEXT),
            workflow
        )
    }
    // Service workflows take their service's lane. The base CONTEXT lists
    // only two services, so the universe here has to know the real ones.
    const serviceContext = {
        ...CONTEXT,
        products: [...CONTEXT.products, 'metrics'],
        services: [...CONTEXT.services, 'agent-proxy', 'integration-service', 'llm-gateway'],
    }
    for (const [workflow, treeFile] of [
        ['ci-llm-gateway.yml', 'services/llm-gateway/src/main.py'],
        ['llm-gateway-cd.yml', 'services/llm-gateway/src/main.py'],
        ['ci-agent-proxy.yml', 'services/agent-proxy/src/index.ts'],
        ['cd-agent-proxy-image.yml', 'services/agent-proxy/src/index.ts'],
        ['ci-integration-service.yml', 'services/integration-service/src/index.ts'],
        ['cd-integration-service-image.yml', 'services/integration-service/src/index.ts'],
        ['ci-oauth-proxy.yml', 'services/oauth-proxy/src/index.ts'],
        ['ci-ml-mirror-image-scrub-container.yml', 'nodejs/src/index.ts'],
    ]) {
        assert.deepEqual(
            computeTargets([`.github/workflows/${workflow}`], serviceContext),
            computeTargets([treeFile], serviceContext),
            workflow
        )
    }
    assert.deepEqual(computeTargets(['.github/workflows/cd-metrics-agent-image.yml'], serviceContext), [
        'fe:product:metrics',
        'py:product:metrics',
    ])
    // The MCP image's readers are the product-surface set, same as the
    // openapi-codegen workflow.
    assert.deepEqual(
        computeTargets(['.github/workflows/cd-mcp-image.yml'], CONTEXT),
        computeTargets(['.github/workflows/ci-openapi-codegen.yml'], CONTEXT)
    )
    // Cross-domain workflows take the union of the families on each side,
    // matching what the same change spelled as files would claim.
    const pythonNodeRust = computeTargets(['mypy.ini', 'rust/Cargo.toml', 'nodejs/src/index.ts'], CONTEXT)
    for (const workflow of ['ci-migrations-service-separation-check.yml', 'ci-proto.yml']) {
        assert.deepEqual(computeTargets([`.github/workflows/${workflow}`], CONTEXT), pythonNodeRust, workflow)
    }
    const rustPython = computeTargets(['mypy.ini', 'rust/Cargo.toml'], CONTEXT)
    for (const workflow of ['build-deltalite.yml', 'ci-deltalite-python.yml', 'build-hogql-parser-rs.yml']) {
        assert.deepEqual(computeTargets([`.github/workflows/${workflow}`], CONTEXT), rustPython, workflow)
    }
    const pythonJavascript = computeTargets(['mypy.ini', '.oxlintrc.json'], CONTEXT)
    for (const workflow of ['build-hogql-parser-npm.yml', 'ci-hog.yml', 'ci-agent-skills.yml']) {
        assert.deepEqual(computeTargets([`.github/workflows/${workflow}`], CONTEXT), pythonJavascript, workflow)
    }
    // The desktop workflow family takes the desktop product's own two lanes,
    // and widens in a context where no such product exists.
    const desktopContext = {
        ...CONTEXT,
        products: [...CONTEXT.products, 'desktop'],
        backendDetachedProducts: new Set(['desktop']),
    }
    assert.deepEqual(
        computeTargets(['.github/workflows/desktop-ci.yml', '.github/workflows/desktop-release.yml'], desktopContext),
        computeTargets(['products/desktop/apps/code/src/main.ts', 'products/desktop/tools/build.py'], desktopContext)
    )
    assert.deepEqual(computeTargets(['.github/workflows/desktop-ci.yml'], CONTEXT), EVERYTHING)
    // The Depot shadows take their canonical twin's domain instead of the
    // .depot/** universal rule, so a shadow-only or paired edit stays on the
    // python lanes.
    assert.deepEqual(
        computeTargets(
            ['.depot/workflows/ci-backend.yml', '.depot/workflows/ci-backend-update-test-timing.yml'],
            CONTEXT
        ),
        python
    )
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
    assert.equal(allKnownTargets({ ...CONTEXT, rustGraph: null }), null)
    assert.equal(allKnownTargets({ ...CONTEXT, services: null }), null)
    assert.equal(computeTargets(['some-new-toplevel/thing.go'], { ...CONTEXT, services: null }), ALL)
    // An explicit-lanes rule cannot validate its names without the full
    // universe, so it widens to the sentinel too.
    assert.equal(computeTargets(['.github/workflows/ci-cli.yml'], { ...CONTEXT, services: null }), ALL)
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

test('a rust path outside every known crate widens', () => {
    assert.deepEqual(computeTargets(['rust/not-a-crate/file.rs'], CONTEXT), EVERYTHING)
})

// A binding crate compiles into a native module the JS workspace imports, so
// the lane cannot stop at rust/. A PR changing the binding and a PR changing
// its caller in nodejs/ must not come out disjoint.
test('a crate that builds an npm package claims the lanes importing it', () => {
    const bindingContext = {
        ...CONTEXT,
        rustGraph: { ...CONTEXT.rustGraph, nativeBindings: new Set(['consumer']) },
    }
    // Reached through the closure rather than directly: `shared` is not itself a
    // binding, but what it compiles into ships inside one.
    const viaDependency = computeTargets(['rust/shared/src/lib.rs'], bindingContext)
    assert.equal(viaDependency.includes('node:ingestion'), true)

    const direct = computeTargets(['rust/consumer/src/lib.rs'], bindingContext)
    assert.equal(direct.includes('node:ingestion'), true)

    // A crate no binding depends on keeps its own lane.
    const unrelated = computeTargets(['rust/unrelated/src/main.rs'], bindingContext)
    assert.deepEqual(unrelated, ['rust:crate:unrelated'])
})

// The cargo lockfile, the manifest, and the sqlx offline data resolve nothing
// outside the cargo workspace, so the lanes they can break are the rust ones
// plus whatever reaches them through a native module, rather than every lane in
// the repo. rust/Cargo.lock is in the list on its fallback: this context carries
// no determinator answer, so it claims the same set. The narrowed case is below.
test('the cargo workspace tripwires claim the rust lanes rather than every lane', () => {
    const bindingContext = {
        ...CONTEXT,
        rustGraph: { ...CONTEXT.rustGraph, nativeBindings: new Set(['consumer']) },
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

// The seeds are the crates the determinator named; computeTargets owns the
// closure over them. Without it, a resolution change in a crate every other
// crate depends on would claim one lane.
test('a narrowed lockfile change still claims the dependents of the crates it named', () => {
    const targets = computeTargets(['rust/Cargo.lock'], { ...CONTEXT, cargoLockCrates: ['shared'] })
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
    const targets = computeTargets(['rust/Cargo.lock'], { ...CONTEXT, cargoLockCrates: [] })
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
        ['a crate the graph does not hold', '["shared", "ghost"]'],
    ]) {
        assert.equal(parseCargoLockCrates(raw, CONTEXT.rustGraph), null, `${name} should read as unknown`)
    }
})

test('a determinator answer the graph agrees with is used as it stands', () => {
    assert.deepEqual(parseCargoLockCrates('["shared"]', CONTEXT.rustGraph), ['shared'])
})

// The determinator's workspace and this script's crate graph are built from the
// same manifests by different code, so a name in one and not the other means one
// of them is wrong. Reads the real graph, which is the only place that can drift.
test('the crate graph holds every crate the determinator can name', () => {
    const { rustGraph } = buildContext(REPO_ROOT)
    const members = fs
        .readFileSync(path.join(REPO_ROOT, 'rust/Cargo.toml'), 'utf8')
        .split(/^\s*\[/m)
        .find((section) => section.startsWith('workspace]'))
        .match(/members\s*=\s*\[([^\]]*)\]/)[1]
        .split(',')
        .map((entry) => entry.trim().replace(/^"|"$/g, ''))
        .filter(Boolean)
    const missing = members.filter((dir) => !rustGraph.byDir.some((crate) => crate.dir === dir))
    assert.deepEqual(missing, [], 'these workspace members are absent from the crate graph')
})

// The two lists below are the same rule written twice, once for the merge queue
// and once for CI's selective builds. Nothing but this test stops them drifting,
// and the failure is silent in both directions: an edge the queue drops lets two
// conflicting PRs merge in parallel.
test('the runtime spawn edges match the determinator package rules', () => {
    const rulesToml = fs.readFileSync(path.join(REPO_ROOT, 'rust/affected-services/determinator-rules.toml'), 'utf8')
    const names = (block, key) => {
        const match = block.match(new RegExp(`${key}\\s*=\\s*\\[([^\\]]*)\\]`))
        return match ? [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort() : []
    }
    const packageRules = rulesToml
        .split(/^\s*\[\[package-rule\]\]\s*$/m)
        .slice(1)
        .map((block) => ({ onAffected: names(block, 'on-affected'), markChanged: names(block, 'mark-changed') }))

    const fromScript = [...RUNTIME_SPAWN_EDGES]
        .map(([spawner, spawned]) => ({ onAffected: [...spawned].sort(), markChanged: [spawner] }))
        .sort((a, b) => a.markChanged[0].localeCompare(b.markChanged[0]))
    const fromRules = packageRules.sort((a, b) => a.markChanged[0].localeCompare(b.markChanged[0]))

    assert.deepEqual(fromScript, fromRules)
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
    const toml = `
[[modules]]
path = "products.beta"
depends_on = ["products.alpha"]
layer = "modules"

[[modules]]
path = "products.gamma"
depends_on = ["products.beta"]
layer = "modules"
`
    const context = { ...CONTEXT, tachGraph: { graph: parseTachModules(toml), tachDependents } }
    assert.deepEqual(computeTargets(['products/alpha/backend/api.py'], context), [
        'py:product:alpha',
        'py:product:beta',
    ])
})

// The base CONTEXT keeps an empty tach graph, so no product is declared in it.
// A product `tach check` does not constrain has no bounded importer set: any
// module may import it, so its change still has to reach every backend lane.
test('a product absent from the tach graph widens to every backend target', () => {
    const targets = computeTargets(['products/gamma/backend/api.py'], CONTEXT)
    assert.equal(targets.includes('py:core'), true)
    for (const product of CONTEXT.products) {
        assert.equal(targets.includes(`py:product:${product}`), true, `expected py:product:${product}`)
    }
})

// The lane only has to answer whether another PR can reference the symbols this
// one changed, and tach.toml answers exactly that. Isolation is the stronger,
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
// repository that pytest.ini ignores and tach.toml never declares. Its
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

// These steer what every suite runs, so they cannot sit in one domain's lane.
test('CI-steering scripts directly under tools/ widen', () => {
    assert.deepEqual(computeTargets(['tools/playwright_spec_selection.py'], CONTEXT), EVERYTHING)
    assert.deepEqual(computeTargets(['tools/snob_backend_test_selection_shadow.py'], CONTEXT), EVERYTHING)
})

// Both are tripwires rather than falling through to the tools/ rule, which
// would give them the python product lanes and nothing else. openapi-codegen
// generates the frontend types from the backend serializers, so it claims both
// sides of the fe/py split, and owners is read by both suites.
test('cross-domain tools are tripwires rather than backend-only', () => {
    assert.deepEqual(
        computeTargets(['tools/openapi-codegen/config.ts'], CONTEXT),
        computeTargets(['frontend/src/products.json'], CONTEXT)
    )
    assert.deepEqual(computeTargets(['tools/owners/posthog_owners/__init__.py'], CONTEXT), EVERYTHING)
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
    assert.deepEqual(computeTargets(['rust/unrelated/src/main.rs', 'README.md'], CONTEXT), ['rust:crate:unrelated'])
})

// hogli build:skills zips products/*/skills/*, and ci-agent-skills.yml gates on
// those paths and on .agents/, so this markdown is a build input, not prose.
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
