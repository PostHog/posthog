#!/usr/bin/env node

// Maps a PR's changed files to the target names Trunk's parallel merge queue
// uses to assign lanes.
//
// THE SAFETY INVARIANT: Trunk runs two PRs in parallel lanes if and only if
// their target sets are disjoint, which means those PRs merge into master
// without ever having been tested together. Reporting extra targets only costs
// parallelism; reporting too few lets conflicting PRs land side by side and
// breaks master. Every rule here is therefore biased toward over-reporting,
// and anything unrecognized falls through to "ALL" (overlaps everything, which
// is the single-lane behavior we had before this script existed).
//
// The bias is relaxed in exactly two places, both bounded by what one PR can
// name in another. The conflict that lanes exist to prevent is semantic rather
// than textual, because a textual one would force a rebase and a retest: PR A
// renames a facade function and updates every current caller, PR B adds a new
// call to the old name, and master breaks on a combination neither run held.
//
//   1. Only a change to a product's declared contract surface seeds the
//      dependent cascade. A file that no module outside the product can import
//      cannot be the shared symbol two PRs disagree about, so a change confined
//      to internals keeps its own product's lane. The surface is the product's
//      own `backend:contract-check` inputs in products/<name>/turbo.json, the
//      same declaration turbo-discover reads to decide whether dependent test
//      suites run, so the two mechanisms cannot drift apart. A product that
//      declares no narrowed inputs cascades on every backend file as before.
//      This makes the declaration load-bearing for correctness: an input list
//      that omits a file other products import puts those products in a
//      parallel lane.
//
//   2. The cascade names direct importers rather than the transitive closure.
//      Only a direct importer can reference the changed product's symbols.
//      ACCEPTED RISK: a conflict mediated through an intermediate product (A
//      changes warehouse_sources, B changes code whose behavior depends on
//      product_analytics, which depends on warehouse_sources) is no longer
//      serialized, and master's post-merge run is the only net for it. The
//      transitive closure was not a usable alternative: a 31-product cycle in
//      tach.toml means every member reaches every other, so any seed inside it
//      expanded to the whole backend and the cascade could not distinguish
//      products at all.
//
// That bias is the opposite of the one in ci-*.yml path filters. Those filters
// decide which tests to run, where an over-broad match wastes runner minutes
// and an under-broad match skips tests. They are tuned to over-run and are NOT
// a safe source for lane assignment: ci-frontend.yml's `frontend` filter
// matches '**/*.md' and '**/*.yaml', so nearly every PR in the repo matches it.
//
// Core targets expand to include every leaf target in their domain, because
// Trunk only has set intersection to express "core overlaps everything
// downstream". A change to posthog/ can break any product, so it reports
// py:core plus every py:product:*, which serializes it against all backend
// work while still running parallel to rust, nodejs, and services.
//
// ACCEPTED RISK: fe:core and py:core are disjoint, so a frontend PR and a
// backend PR can merge in parallel. The E2E suite exercises both together and
// runs on either kind of change, which means a combination neither PR's own run
// covered can still break master. That residual risk is inherent to parallel
// queues rather than specific to these rules. If it shows up in practice, the
// knob is an `e2e` target emitted for every change matching the E2E trigger
// paths in ci-e2e-playwright.yml, which puts all such PRs back in one lane.
//
// Input:  changed file paths, one per line, on stdin
// Output: JSON on stdout, either the string "ALL" or an array of target names.
//         A change set of nothing but prose reports the single "prose" lane,
//         which overlaps only other prose-only PRs.
//         Diagnostics on stderr

const fs = require('fs')
const path = require('path')

const ALL = 'ALL'

const REPO_ROOT = path.resolve(__dirname, '..', '..')

// Files whose effect crosses every lane boundary: lockfiles and workspace
// manifests (a dependency bump changes what every tree compiles against),
// cross-language contracts (a schema or proto change lands in generated code
// on both sides), the module graphs that this script and turbo-discover read,
// and the CI definitions that decide what runs for everyone.
const TRIPWIRES = [
    'pnpm-lock.yaml',
    'pnpm-workspace.yaml',
    'package.json',
    'uv.lock',
    'pyproject.toml',
    'requirements.txt',
    'requirements-dev.txt',
    'rust/Cargo.lock',
    'rust/Cargo.toml',
    'rust/.sqlx/**',
    'tach.toml',
    'turbo.json',
    'hogli.yaml',
    '.nvmrc',
    '.github/**',
    'docker-compose*.yml',
    'Dockerfile*',
    'proto/**',
    // schema.json generates posthog/schema.py, and both sides are committed.
    'frontend/src/queries/schema.json',
    'posthog/schema.py',
    // products.json is loaded at runtime by posthog/products.py and generated
    // from every product's manifest.
    'frontend/src/products.json',
    'products/*/manifest.tsx',
    // Generates the frontend API types from the backend serializers, so a
    // change lands on both sides of the fe/py split at once.
    'tools/openapi-codegen/**',
    // Ownership data read by the backend, frontend, and script suites alike.
    'tools/owners/**',
    'conftest.py',
    'pytest.ini',
    'mypy.ini',
    '.test_durations',
    '.test_quarantine.json',
    // bin/ appears in the backend, frontend, and E2E path filters alike.
    'bin/**',
    'patches/**',
    'tsconfig.json',
    'tsconfig.*.json',
    'babel.config.js',
    'webpack.config.js',
    '.oxlintrc.json',
    '.oxfmtrc*',
]

// Subdirectories of common/ that belong to a single domain. Anything else
// under common/ is deliberately absent so it falls through to ALL rather than
// being guessed at.
const COMMON_PYTHON = ['hogql_parser', 'hogvm', 'ingestion', 'migration_utils', 'plugin_transpiler', 'alerting']
const COMMON_FRONTEND = ['esbuilder', 'storybook', 'tailwind', 'replay-shared', 'replay-headless']

// Tools that own their whole test story and that no suite imports, so they can
// hold a lane of their own. Everything else under tools/ falls through to the
// backend lanes, which keeps a newly added tool over-reporting until someone
// establishes it belongs here.
//
// hogli and hogli-commands are deliberately absent: ci-backend.yml drives the
// suite through hogli, and posthog/conftest.py imports
// hogli_commands.quarantine.pytest_support on every pytest run.
const TOOLS_INDEPENDENT = [
    'phrocs',
    'hogbox-preview',
    'traffic-sim',
    'hedgebox-dummy',
    'pr-approval-agent',
    'query-performance-ai',
    'infra-scripts',
]

// Supports the three forms used in TRIPWIRES: `**` spanning directories, `*`
// within a single path segment, and literal names. The two star forms are
// parked on placeholders first so neither rewrites the other's output.
const GLOBSTAR_SLASH = '\u0000'
const GLOBSTAR = '\u0001'

function globToRegExp(glob) {
    const body = glob
        .replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\*\*\//g, GLOBSTAR_SLASH)
        .replace(/\*\*/g, GLOBSTAR)
        .replace(/\*/g, '[^/]*')
        .split(GLOBSTAR_SLASH)
        .join('(?:.*/)?')
        .split(GLOBSTAR)
        .join('.*')
    return new RegExp(`^${body}$`)
}

const TRIPWIRE_MATCHERS = TRIPWIRES.map(globToRegExp)

function isTripwire(file) {
    return TRIPWIRE_MATCHERS.some((re) => re.test(file))
}

function listProducts(repoRoot) {
    return fs
        .readdirSync(path.join(repoRoot, 'products'), { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort()
}

// A product is isolated when it declares a backend:contract-check script, the
// same signal turbo-discover uses to decide a product can be tested alone.
// Non-isolated products have no narrowed contract, so a change in one is
// treated as a core change.
function listIsolatedProducts(repoRoot, products) {
    const isolated = new Set()
    for (const product of products) {
        const manifest = path.join(repoRoot, 'products', product, 'package.json')
        if (!fs.existsSync(manifest)) {
            continue
        }
        const parsed = JSON.parse(fs.readFileSync(manifest, 'utf8'))
        if (parsed.scripts && parsed.scripts['backend:contract-check']) {
            isolated.add(product)
        }
    }
    return isolated
}

// --- Contract surfaces ---

const CONTRACT_TASK = 'backend:contract-check'

// turbo.json permits comments, which JSON.parse rejects. Strip them outside
// string literals so a `//` inside a glob survives.
function stripJsonComments(text) {
    let out = ''
    let inString = false
    let escaped = false
    for (let i = 0; i < text.length; i++) {
        const char = text[i]
        const next = text[i + 1]
        if (inString) {
            out += char
            if (escaped) {
                escaped = false
            } else if (char === '\\') {
                escaped = true
            } else if (char === '"') {
                inString = false
            }
            continue
        }
        if (char === '"') {
            inString = true
            out += char
            continue
        }
        if (char === '/' && next === '/') {
            while (i < text.length && text[i] !== '\n') {
                i++
            }
            out += '\n'
            continue
        }
        if (char === '/' && next === '*') {
            i += 2
            while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) {
                i++
            }
            i++
            continue
        }
        out += char
    }
    return out
}

// Compiles a task's `inputs` into a predicate over product-relative paths. A
// path is contract when at least one positive glob matches it and no negated
// one does, matching how Turbo reads the same list.
function compileContractMatcher(inputs) {
    const include = []
    const exclude = []
    for (const input of inputs) {
        const negated = input.startsWith('!')
        const glob = negated ? input.slice(1) : input
        // An input reaching outside the product (../../uv.lock and the like)
        // cannot be expressed as a product-relative path. Dropping it is safe
        // because every such file in use today is already a tripwire or lands
        // in py:core, both of which overlap this product's lane anyway.
        if (glob.startsWith('../')) {
            continue
        }
        if (negated) {
            exclude.push(globToRegExp(glob))
        } else {
            include.push(globToRegExp(glob))
        }
    }
    if (include.length === 0) {
        return null
    }
    return (relativePath) =>
        include.some((re) => re.test(relativePath)) && !exclude.some((re) => re.test(relativePath))
}

// Only products that narrow `backend:contract-check` in their own turbo.json get
// an entry. Absence means "every backend file is contract", so a product that
// has not declared a surface, or whose turbo.json cannot be read, keeps
// cascading on every backend change.
function loadContractSurfaces(repoRoot, products) {
    const surfaces = new Map()
    for (const product of products) {
        const manifest = path.join(repoRoot, 'products', product, 'turbo.json')
        if (!fs.existsSync(manifest)) {
            continue
        }
        let inputs
        try {
            const parsed = JSON.parse(stripJsonComments(fs.readFileSync(manifest, 'utf8')))
            const tasks = parsed.tasks || parsed.pipeline || {}
            inputs = (tasks[CONTRACT_TASK] || {}).inputs
        } catch (error) {
            console.error(
                `Could not read products/${product}/turbo.json (${error.message}); every backend file counts as its contract`
            )
            continue
        }
        if (!Array.isArray(inputs)) {
            continue
        }
        const matcher = compileContractMatcher(inputs)
        if (matcher) {
            surfaces.set(product, matcher)
        }
    }
    return surfaces
}

// The files that define the gate for their own product: turbo.json holds the
// contract inputs, package.json decides whether the product is isolated at all.
// Neither is importable, so the surface test would call them internal, and both
// are read from the PR's own tree. A change that drops a path from the contract
// and edits a file under that path in the same commit would then be gated
// against its own new, narrower contract and keep the lane to itself, which is
// exactly when the dependents most need to be tested alongside it.
const CONTRACT_DECLARATIONS = ['turbo.json', 'package.json']

function touchesContractSurface(product, file, contractSurfaces) {
    const relativePath = file.slice(`products/${product}/`.length)
    if (CONTRACT_DECLARATIONS.includes(relativePath)) {
        return true
    }
    const matcher = contractSurfaces.get(product)
    if (!matcher) {
        return true
    }
    return matcher(relativePath)
}

// --- Rust crate graph ---

// Discovers workspace crates as (directory, crate name) pairs. Crate names can
// differ from directory names, and file paths only carry the directory, so both
// are needed to translate a changed path into a graph node.
function discoverRustCrates(repoRoot) {
    const crates = []
    const walk = (dir, depth) => {
        if (depth > 3) {
            return
        }
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (entry.name === 'target' || entry.name === '.git' || entry.name.startsWith('.')) {
                continue
            }
            const full = path.join(dir, entry.name)
            if (entry.isDirectory()) {
                walk(full, depth + 1)
            } else if (entry.name === 'Cargo.toml') {
                const relative = path.relative(path.join(repoRoot, 'rust'), dir)
                if (!relative) {
                    continue
                }
                const text = fs.readFileSync(full, 'utf8')
                const name = parseCrateName(text)
                if (name) {
                    crates.push({ dir: relative, name, text })
                }
            }
        }
    }
    walk(path.join(repoRoot, 'rust'), 0)
    return crates
}

function parseCrateName(tomlText) {
    const packageSection = tomlText.split(/^\s*\[/m).find((section) => section.startsWith('package]'))
    if (!packageSection) {
        return null
    }
    const match = packageSection.match(/^\s*name\s*=\s*"([^"]+)"/m)
    return match ? match[1] : null
}

// Collects the intra-workspace crates a Cargo.toml depends on. Dependencies
// declared as `foo.workspace = true` resolve through the workspace table to the
// same crate name, so matching on the dependency key covers both that form and
// a direct path dependency.
//
// A `package = "..."` key renames the dependency, so the real crate is that
// value rather than the key. Most uses point at an external crate under a
// version-suffixed alias (prost14 = { package = "prost" }), which contributes
// no intra-workspace edge, but resolving through it is what keeps a renamed
// workspace crate from being dropped.
// Classifies a section header, returning null when it carries no dependencies.
// Cargo spells dependency sections four ways, and the ones where the dependency
// name lives in the header rather than in a body key are easy to miss:
//
//   [dependencies]                                  -> body keys are the names
//   [dev-dependencies] / [build-dependencies]       -> body keys are the names
//   [target.'cfg(...)'.dependencies]                -> body keys are the names
//   [dependencies.<name>]                           -> the header carries the name
//
// `[workspace.dependencies]` is excluded: it declares versions for the whole
// workspace rather than this crate's own edges.
function dependencySectionName(header) {
    if (header.startsWith('workspace.')) {
        return null
    }
    const match = header.match(/(?:^|\.)(?:dev-|build-)?dependencies(?:\.(.+))?$/)
    if (!match) {
        return null
    }
    return { named: match[1] ? match[1].replace(/^["']|["']$/g, '') : null }
}

function parseCrateDependencies(tomlText, crateNames) {
    const deps = new Set()
    const sections = tomlText.split(/^\s*\[/m)
    for (const section of sections) {
        const header = section.split(']')[0]
        const dependencySection = dependencySectionName(header)
        if (!dependencySection) {
            continue
        }
        const body = section.slice(section.indexOf(']') + 1)

        // In a [dependencies.<name>] table the body holds attributes (path,
        // version, features), not dependency names, so scanning its keys would
        // both miss the real edge and risk matching an attribute that happens
        // to share a crate name.
        if (dependencySection.named) {
            const renamed = body.match(/^\s*package\s*=\s*"([^"]+)"/m)
            const name = renamed ? renamed[1] : dependencySection.named
            if (crateNames.has(name)) {
                deps.add(name)
            }
            continue
        }

        for (const line of body.split('\n')) {
            const stripped = line.replace(/#.*$/, '').trim()
            if (!stripped) {
                continue
            }
            const renamed = stripped.match(/\bpackage\s*=\s*"([^"]+)"/)
            if (renamed) {
                if (crateNames.has(renamed[1])) {
                    deps.add(renamed[1])
                }
                continue
            }
            const match = stripped.match(/^([A-Za-z0-9_-]+)\s*(?:\.[A-Za-z-]+)?\s*=/)
            if (match && crateNames.has(match[1])) {
                deps.add(match[1])
            }
        }
    }
    return [...deps]
}

// Returns null when the crate graph can't be built. Callers must treat null as
// "unknown dependents" and report every rust target, never as "no dependents".
function loadRustGraph(repoRoot) {
    try {
        const crates = discoverRustCrates(repoRoot)
        if (crates.length === 0) {
            return null
        }
        const crateNames = new Set(crates.map((crate) => crate.name))
        const dependsOn = new Map()
        for (const crate of crates) {
            dependsOn.set(crate.name, parseCrateDependencies(crate.text, crateNames))
        }
        // Longest directory first so rust/common/hogvm resolves to its own crate
        // rather than to rust/common.
        const byDir = crates
            .map((crate) => ({ dir: crate.dir, name: crate.name }))
            .sort((a, b) => b.dir.length - a.dir.length)
        return { dependsOn, byDir }
    } catch (error) {
        console.error(`Rust crate graph unavailable (${error.message}); reporting every rust target`)
        return null
    }
}

function reverseClosure(seeds, dependsOn) {
    const reverse = new Map()
    for (const [node, deps] of dependsOn) {
        for (const dep of deps) {
            if (!reverse.has(dep)) {
                reverse.set(dep, [])
            }
            reverse.get(dep).push(node)
        }
    }
    const reached = new Set(seeds)
    const queue = [...seeds]
    while (queue.length > 0) {
        const current = queue.shift()
        for (const dependent of reverse.get(current) || []) {
            if (reached.has(dependent)) {
                continue
            }
            reached.add(dependent)
            queue.push(dependent)
        }
    }
    return [...reached]
}

// --- Target computation ---

const pyProduct = (product) => `py:product:${product}`
const feProduct = (product) => `fe:product:${product}`
const rustCrate = (crate) => `rust:crate:${crate}`

function computeTargets(changedFiles, context) {
    const { products, isolatedProducts, rustGraph, tachGraph, contractSurfaces = new Map() } = context
    const targets = new Set()

    const allPyProducts = () => {
        targets.add('py:core')
        for (const product of products) {
            targets.add(pyProduct(product))
        }
    }
    const allFeProducts = () => {
        targets.add('fe:core')
        for (const product of products) {
            targets.add(feProduct(product))
        }
    }

    const changedIsolatedProducts = new Set()
    let inertFiles = 0

    for (const file of changedFiles) {
        if (isTripwire(file)) {
            return ALL
        }

        const segments = file.split('/')
        const top = segments[0]

        // Prose compiles into nothing and no PR can disagree with another about
        // it, so it claims no lane at all rather than the shared one it used to
        // get, which serialized any two PRs that happened to touch a markdown
        // file. Classified before the directory rules that would otherwise pull
        // a README under posthog/ into the backend lane.
        //
        // The exception is markdown that is a build input: `hogli build:skills`
        // zips products/*/skills/*, and ci-agent-skills.yml gates on those paths
        // and on .agents/. Both fall through to their directory rules below.
        const isSkillSource = top === '.agents' || (top === 'products' && segments[2] === 'skills')
        if (/\.mdx?$/.test(file) && !isSkillSource) {
            inertFiles++
            continue
        }

        if (top === 'posthog' || (top === 'ee' && segments[1] !== 'frontend')) {
            allPyProducts()
            continue
        }
        if (top === 'frontend' || (top === 'ee' && segments[1] === 'frontend') || top === 'packages') {
            allFeProducts()
            continue
        }
        // A spec change cannot break app code, but it runs against whatever
        // frontend lands beside it, so it shares the frontend lanes.
        if (top === 'playwright') {
            allFeProducts()
            continue
        }
        if (top === 'nodejs') {
            targets.add('node:ingestion')
            continue
        }
        if (top === 'services' && segments.length > 1) {
            targets.add(`svc:${segments[1]}`)
            continue
        }
        // docs/ is prose, which the markdown rule above has already taken, with
        // one exception: docs/onboarding is the @posthog/docs-onboarding
        // workspace package that frontend/package.json depends on, so its
        // sources compile into the app. Anything else non-prose under docs/ is
        // unclassified and falls through to ALL at the end of the loop.
        if (top === 'docs' && segments[1] === 'onboarding') {
            allFeProducts()
            continue
        }
        if (top === '.agents') {
            targets.add('agents')
            continue
        }
        if (top === 'tools') {
            // A file sitting directly under tools/ rather than inside a tool's
            // own directory is one of the CI-steering scripts (backend test
            // selection, playwright spec selection, the selection verdict).
            // Those decide what runs across every suite, so they widen fully.
            if (segments.length < 3) {
                return ALL
            }
            if (TOOLS_INDEPENDENT.includes(segments[1])) {
                targets.add(`tools:${segments[1]}`)
                continue
            }
            allPyProducts()
            continue
        }
        if (top === 'common' && segments.length > 1) {
            if (COMMON_PYTHON.includes(segments[1])) {
                allPyProducts()
                continue
            }
            if (COMMON_FRONTEND.includes(segments[1])) {
                allFeProducts()
                continue
            }
            return ALL
        }
        if (top === 'rust') {
            if (!rustGraph) {
                targets.add('rust:unresolved')
                continue
            }
            const crate = rustGraph.byDir.find(
                (entry) => file.startsWith(`rust/${entry.dir}/`) || file === `rust/${entry.dir}`
            )
            if (!crate) {
                return ALL
            }
            targets.add(rustCrate(crate.name))
            continue
        }
        if (top === 'products' && segments.length > 2) {
            const product = segments[1]
            if (!products.includes(product)) {
                return ALL
            }
            const isBackend = segments[2] === 'backend' || file.endsWith('.py')
            const isFrontend = segments[2] === 'frontend' || /\.tsx?$/.test(file)

            if (isFrontend || (!isBackend && !isFrontend)) {
                targets.add(feProduct(product))
            }
            if (isBackend || (!isBackend && !isFrontend)) {
                if (isolatedProducts.has(product)) {
                    targets.add(pyProduct(product))
                    if (touchesContractSurface(product, file, contractSurfaces)) {
                        changedIsolatedProducts.add(product)
                    }
                } else {
                    allPyProducts()
                }
            }
            continue
        }

        // Nothing claimed this path. Defaulting to an empty target set would
        // read as "parallel with everything", which is the one failure mode
        // that silently breaks master, so widen to ALL instead.
        return ALL
    }

    // Naming a dependent's target is all a lane needs: it puts the two PRs in
    // the same lane so they are tested together. Isolation governs whether a
    // product's own change can be tested alone, which is a different question,
    // so a non-isolated dependent is named here rather than widening to every
    // backend target. Only 14 of the products declare a contract check, so
    // widening on each of them would collapse every cascade to the full set.
    //
    // The seeds are the products whose contract surface changed, and the
    // dependents are one hop deep. See the two numbered narrowings at the top
    // of this file for what that gives up.
    if (changedIsolatedProducts.size > 0) {
        const dependents = tachDependentProducts([...changedIsolatedProducts], tachGraph)
        if (dependents === null) {
            allPyProducts()
        } else {
            for (const dependent of dependents) {
                targets.add(pyProduct(dependent))
            }
        }
    }

    if (rustGraph && [...targets].some((target) => target.startsWith('rust:crate:'))) {
        const seeds = [...targets]
            .filter((target) => target.startsWith('rust:crate:'))
            .map((target) => target.slice('rust:crate:'.length))
        for (const crate of reverseClosure(seeds, rustGraph.dependsOn)) {
            targets.add(rustCrate(crate))
        }
    }

    if (targets.has('rust:unresolved')) {
        targets.delete('rust:unresolved')
        if (rustGraph) {
            for (const crate of rustGraph.dependsOn.keys()) {
                targets.add(rustCrate(crate))
            }
        } else {
            return ALL
        }
    }

    if (targets.size === 0) {
        // A change set of nothing but prose overlaps only other prose. Trunk
        // does not document what it does with an empty target list, and the one
        // documented rule is that a PR is not processed until its targets are
        // uploaded, so a lane of its own avoids betting a docs PR's ability to
        // enter the queue on undocumented behavior. This is deliberately not
        // added per file: emitting it alongside real lanes is what made the old
        // docs target serialize two PRs whose only overlap was a README.
        //
        // Anything else that reaches an empty set contains a path no rule
        // claimed, which is the failure mode that silently breaks master, so it
        // still widens to ALL.
        return inertFiles === changedFiles.length ? ['prose'] : ALL
    }
    return [...targets].sort()
}

// tach.toml is the enforced Python module graph (`tach check` runs in CI, so it
// cannot drift from what is importable). Turbo-style dashed names cross the
// boundary in both directions; product directories are underscored.
function tachDependentProducts(changedProducts, tachGraph) {
    if (!tachGraph) {
        return null
    }
    try {
        const { tachDependents } = tachGraph
        return tachDependents(
            changedProducts.map((product) => product.replace(/_/g, '-')),
            tachGraph.graph,
            { direct: true }
        ).map((product) => product.replace(/-/g, '_'))
    } catch (error) {
        console.error(`Dependent cascade failed (${error.message}); widening to all backend targets`)
        return null
    }
}

function loadTachGraph(repoRoot) {
    try {
        const { parseTachModules, tachDependents } = require('./turbo-discover')
        const text = fs.readFileSync(path.join(repoRoot, 'tach.toml'), 'utf8')
        return { graph: parseTachModules(text), tachDependents }
    } catch (error) {
        console.error(`tach.toml graph unavailable (${error.message}); backend changes widen to all products`)
        return null
    }
}

function buildContext(repoRoot) {
    const products = listProducts(repoRoot)
    return {
        products,
        isolatedProducts: listIsolatedProducts(repoRoot, products),
        contractSurfaces: loadContractSurfaces(repoRoot, products),
        rustGraph: loadRustGraph(repoRoot),
        tachGraph: loadTachGraph(repoRoot),
    }
}

module.exports = {
    computeTargets,
    buildContext,
    compileContractMatcher,
    globToRegExp,
    isTripwire,
    parseCrateDependencies,
    parseCrateName,
    reverseClosure,
    stripJsonComments,
    ALL,
}

if (require.main === module) {
    let result
    try {
        const changedFiles = fs
            .readFileSync(0, 'utf8')
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean)
        if (changedFiles.length === 0) {
            console.error('No changed files on stdin; reporting ALL')
            result = ALL
        } else {
            result = computeTargets(changedFiles, buildContext(REPO_ROOT))
        }
    } catch (error) {
        // Any unexpected failure has to widen rather than narrow, because a
        // partial target list is indistinguishable to Trunk from a correct one.
        console.error(`Target computation failed (${error.stack}); reporting ALL`)
        result = ALL
    }
    if (Array.isArray(result)) {
        console.error(`Computed ${result.length} target(s): ${JSON.stringify(result)}`)
    }
    process.stdout.write(JSON.stringify(result))
}
