#!/usr/bin/env node

// Maps a PR's changed files to the target names Trunk's parallel merge queue
// uses to assign lanes.
//
// THE SAFETY INVARIANT: Trunk runs two PRs in parallel lanes if and only if
// their target sets are disjoint, which means those PRs merge into master
// without ever having been tested together. Reporting extra targets only costs
// parallelism; reporting too few lets conflicting PRs land side by side and
// breaks master. Every rule here is therefore biased toward over-reporting,
// and anything unrecognized widens to every known target (the single-lane
// behavior we had before this script existed).
//
// Widening enumerates that set rather than emitting Trunk's "ALL" sentinel.
// The intersection Trunk computes is identical, but the uploaded list says
// which lanes the PR claimed, so the telemetry can compare it against the lanes
// the PR should have claimed. "ALL" is kept for the cases where the set cannot
// be built at all — an unreadable crate graph or services/ listing here, and a
// failed diff in the workflow, which never reaches this script. That is a
// different statement from "everything": it means "unknown".
//
// The bias is relaxed in exactly two places, both bounded by what one PR can
// name in another. The conflict that lanes exist to prevent is semantic rather
// than textual, because a textual one would force a rebase and a retest: PR A
// renames a facade function and updates every current caller, PR B adds a new
// call to the old name, and master breaks on a combination neither run held.
//
//   1. A product change claims its own lane plus its direct importers, rather
//      than every backend lane. tach.toml is the enforced Python module graph
//      (`tach check` runs in CI), so for a product it declares, the modules
//      that may import it are exactly the ones listing it in `depends_on`. A
//      product absent from that graph is unconstrained and still widens.
//
//      This does NOT require the product to be isolated. Isolation is the
//      stronger claim that a change inside the product can only break the
//      product's own tests, which is what lets CI skip the full Django suite,
//      and products/architecture.md is explicit that tach cannot prove it:
//      cross-cutting tests reach a product's endpoints by URL, in process,
//      with no import for any graph to see. A lane only has to answer whether
//      another PR can reference the symbols this one changed, which is the
//      import half that tach does enforce. So a product too unsealed to skip
//      the suite still has a bounded importer set, and gets a lane from it.
//
//      Which of the product's own files seed that cascade is the narrower
//      question isolation does govern. An isolated product declares a contract
//      surface as its `backend:contract-check` inputs in products/<name>/turbo.json.
//      This is the same declaration turbo-discover reads to decide whether dependent
//      test suites run, so the two mechanisms cannot drift apart. A change confined
//      to its internals keeps its own lane without cascading. This makes the
//      declaration load-bearing for
//      correctness: an input list that omits a file other products import puts
//      those products in a parallel lane. A product that declares no narrowed
//      inputs, isolated or not, cascades on every backend file.
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
// Output: JSON on stdout, an array of target names, or the string "ALL" when
//         the target universe could not be enumerated. A change set of nothing
//         but prose reports the single "prose" lane, which overlaps only other
//         prose-only PRs.
//         Diagnostics on stderr

const fs = require('fs')
const path = require('path')

const ALL = 'ALL'

const REPO_ROOT = path.resolve(__dirname, '..', '..')

// Files whose effect crosses lane boundaries: lockfiles and workspace
// manifests (a dependency bump changes what every tree compiles against),
// cross-language contracts (a schema or proto change lands in generated code
// on both sides), the module graphs that this script and turbo-discover read,
// and the CI definitions that decide what runs for everyone.
//
// Each entry carries the blast radius the file can be held to, and `universal`
// is the honest answer whenever that radius is not confidently narrower. The
// three toolchain domains are supersets by construction: `python` claims every
// lane that runs Python, `javascript` every lane that runs TypeScript or
// JavaScript, `rust` every crate. A domain never names less than the file can
// break; it only stops asserting a radius the file does not have, which is what
// keeps a frontend lint rule from serializing against Rust. `product-surface`
// is the one domain named for its readers rather than for a language, because
// the files it covers have a small enumerable set of them.
//
// Entries are matched in order and the first match wins, so a narrower entry
// has to precede the tree it sits in. A `null` domain is an explicit
// non-tripwire: the file falls through to the ordinary directory rules below.
const UNIVERSAL = 'universal'
const PYTHON = 'python'
const JAVASCRIPT = 'javascript'
const RUST = 'rust'

// The product manifests and the artifacts generated from them. Not a toolchain
// domain: it names the two lane families that read that data rather than a
// language, and it exists because `universal` was claiming lanes no reader of
// those files can reach.
const PRODUCT_SURFACE = 'product-surface'

// The proto trees, named for their consumers for the same reason. Every
// consumer generates stubs, so the set is enumerable: tonic builds the rust
// ones on `cargo build`, and the personhog stubs are checked in for both python
// and nodejs. Resolved per tree rather than per file, against PROTO_TREES.
const PROTO = 'proto'

// Resolved per file from the rule's own `languages:` declaration rather than
// from its path, so it cannot be expressed as a static domain here.
const SEMGREP = 'semgrep'

// rust/Cargo.lock, answered by the cargo determinator rather than by the path.
// Its own domain because the answer is a crate list rather than a fixed set of
// lanes, and it degrades to RUST when that list is absent.
const CARGO_LOCK = 'cargo-lock'

const TRIPWIRE_RULES = [
    // Markdown in these trees compiles into nothing and no suite reads it, so
    // it is prose like any other. Ahead of the trees themselves, which would
    // otherwise read a pull request template as a repo-wide CI change.
    ['.github/**/*.md', null],
    ['.semgrep/**/*.md', null],

    // The lane rules themselves, and the graphs they read. Two PRs that
    // disagree about the partition cannot be safely placed in it, which is the
    // self-gating hazard CONTRACT_DECLARATIONS is here for, so these stay
    // universal however narrow the rest of their diff looks.
    ['.github/scripts/trunk-impacted-targets*.js', UNIVERSAL],
    ['.github/scripts/trunk-lane-telemetry*.js', UNIVERSAL],
    ['.github/scripts/turbo-discover*.js', UNIVERSAL],
    ['.github/workflows/trunk-impacted-targets.yml', UNIVERSAL],
    ['turbo.json', UNIVERSAL],

    // tach.toml is one of those graphs, so it carries the same self-gating
    // hazard, but every edge it can move lands on a python lane: `tach check`
    // runs in ci-backend.yml, and the two readers of the graph, this script and
    // turbo-discover, use it only to cascade python product lanes. `python`
    // claims all of them, so a PR editing the graph still overlaps every PR
    // whose lanes were computed against the old one.
    ['tach.toml', PYTHON],

    // A workflow decides which suites run, so one that defines a single
    // language's suite can be held to that language's lanes. Everything else
    // under .github/ stays universal: the list grows by decision, and a
    // workflow nobody has placed here keeps the old radius.
    ['.github/workflows/ci-frontend.yml', JAVASCRIPT],
    ['.github/workflows/ci-storybook.yml', JAVASCRIPT],
    ['.github/workflows/ci-storybook-update-test-timing.yml', JAVASCRIPT],
    ['.github/workflows/ci-nodejs.yml', JAVASCRIPT],
    ['.github/workflows/ci-nodejs-container.yml', JAVASCRIPT],
    ['.github/workflows/ci-mcp.yml', JAVASCRIPT],
    ['.github/workflows/ci-backend.yml', PYTHON],
    ['.github/workflows/ci-backend-update-test-timing.yml', PYTHON],
    ['.github/workflows/ci-backend-shadow-drift.yml', PYTHON],
    ['.github/workflows/ci-dagster.yml', PYTHON],
    ['.github/workflows/ci-rust.yml', RUST],
    ['.github/workflows/ci-rust-flags-integration.yml', RUST],

    // Lint rules that run repo-wide: a new rule fails code that merged in a
    // parallel lane, which is the same conflict .oxlintrc.json is here for. The
    // radius is the languages the rule matches, and semgrep requires every rule
    // to declare them, so the declaration is a sound source. A rule file that
    // does not parse, names a language with no lane mapping, or spans more than
    // one domain falls back to universal. The .py/.ts files beside the rules
    // are its test fixtures, which can only exercise their own language.
    ['.semgrep/**/*.yaml', SEMGREP],
    ['.semgrep/**/*.yml', SEMGREP],
    ['.semgrep/**/*.py', PYTHON],
    ['.semgrep/**/*.ts', JAVASCRIPT],
    ['.semgrep/**/*.tsx', JAVASCRIPT],
    ['.semgrep/**', UNIVERSAL],

    // Toolchain configuration for a single language: a compiler, linter, or
    // formatter setting can only fail the code that tool reads.
    ['tsconfig.json', JAVASCRIPT],
    ['tsconfig.*.json', JAVASCRIPT],
    ['babel.config.js', JAVASCRIPT],
    ['webpack.config.js', JAVASCRIPT],
    ['.oxlintrc.json', JAVASCRIPT],
    ['.oxfmtrc*', JAVASCRIPT],
    ['.nvmrc', JAVASCRIPT],
    ['postcss.config.js', JAVASCRIPT],
    ['.stylelintrc.js', JAVASCRIPT],
    ['.stylelintignore', JAVASCRIPT],
    ['.kearc', JAVASCRIPT],
    // State the posthog-cli schema command writes for this repo, recording the
    // hash and output path of the generated event definitions. cli/ reads and
    // rewrites it (cli/src/experimental/schema.rs), and its only generated
    // output here is frontend/src/lib/posthog-typed.ts, both of which the
    // javascript domain covers. Nothing in Python reads it.
    ['posthog.json', JAVASCRIPT],
    ['mypy.ini', PYTHON],
    ['pytest.ini', PYTHON],
    ['conftest.py', PYTHON],
    ['manage.py', PYTHON],
    ['pytest_boot_gc.py', PYTHON],
    ['dagster_cloud.yaml', PYTHON],
    // Serves the Django app in the production image, so the module paths it
    // names are the ones a Python change can rename out from under it.
    ['unit.json.tpl', PYTHON],

    // The pnpm workspace's lockfile and manifests. A resolution change here can
    // red the python lanes, which install the root package and drive pytest
    // through `pnpm turbo run backend:test`, but a lane is not what catches
    // that: the ci-*.yml path filters decide what runs, so the break lands in
    // the PR's own run. A lane only has to hold the interaction with a second
    // PR, and the shape that reaches a python lane is lockfile drift against a
    // workspace package.json, which needs both PRs to edit pnpm-lock.yaml and
    // so surfaces as a textual conflict git forces a rebase for.
    ['pnpm-lock.yaml', JAVASCRIPT],
    ['pnpm-workspace.yaml', JAVASCRIPT],
    ['package.json', JAVASCRIPT],
    // The python lockfile and manifests, on the same reasoning. Every section
    // of pyproject.toml configures a python tool, and nothing in the pnpm
    // workspace or the cargo one resolves against either file: the two pyo3
    // crates install from PyPI rather than from this checkout, which the
    // uv.lock path-source test holds in place.
    ['uv.lock', PYTHON],
    ['pyproject.toml', PYTHON],
    // The cargo workspace's own lockfile and manifest. What kept them universal
    // was the three crates that are also pnpm packages, and the `rust` domain
    // now names the lanes consuming those, so the radius is covered without
    // claiming every lane in the repo. The workspace's two pyo3 crates do not
    // extend the radius the same way: hogql_parser_rs and deltalite-python are
    // published to PyPI by their own workflows and pinned by version in
    // pyproject.toml, so the python suites install a released wheel rather than
    // building either from this checkout. A resolution change reaches a python
    // lane only through the version bump, which is a pyproject.toml and uv.lock
    // edit claiming those lanes above.
    //
    // The lockfile narrows further than the manifest, because it states the
    // resolution rather than the request. CARGO_LOCK takes the crate list from
    // the same determinator ci-rust.yml runs, so a dependency added for one
    // crate stops claiming the whole workspace. rust/Cargo.toml stays on the
    // whole domain: a workspace-wide feature or version request can change how
    // a shared dependency compiles for every crate, and a manifest edit that
    // moves no resolution leaves no lockfile diff for the determinator to read.
    ['rust/Cargo.lock', CARGO_LOCK],
    ['rust/Cargo.toml', RUST],
    ['rust/.sqlx/**', RUST],
    ['hogli.yaml', UNIVERSAL],
    ['.github/**', UNIVERSAL],
    ['docker-compose*.yml', UNIVERSAL],
    ['Dockerfile*', UNIVERSAL],
    // Decides what lands in the build context of every image built from the
    // repository root, so it belongs with the Dockerfiles above.
    ['.dockerignore', UNIVERSAL],
    ['proto/**', PROTO],
    ['frontend/src/queries/schema.json', PRODUCT_SURFACE],
    ['posthog/schema.py', PRODUCT_SURFACE],
    // A manifest publishes its product's urls, routes, and tree items into
    // globals any other product's frontend can reference, and build-products.mjs
    // compiles every manifest into products.json, which posthog/products.py
    // loads at runtime and user_product_list.py keys off the `path` values of.
    // So both sides of the fe/py split can hold a reference to what one manifest
    // renames, and both claim their full lane family here.
    //
    // Outside those two the only reader is services/mcp, which the lane function
    // names. Nothing under rust/ or nodejs/ reads products.json or globs the
    // manifests, so `universal` was asserting a radius these files do not have.
    // The generated products.tsx and productScenes.tsx are deliberately absent:
    // they have no Python reader, and the frontend rule below already gives them
    // the frontend lanes.
    ['frontend/src/products.json', PRODUCT_SURFACE],
    ['products/*/manifest.tsx', PRODUCT_SURFACE],
    // Generates the frontend API types from the backend serializers, so a
    // change lands on both sides of the fe/py split at once.
    ['tools/openapi-codegen/**', PRODUCT_SURFACE],
    // Ownership data read by the backend, frontend, and script suites alike.
    // The root owners.yaml is the fallback every path resolves through when no
    // nearer file claims it, so it has the same readers as the tooling. A
    // product's own owners.yaml is not here: it keeps its product lane.
    ['tools/owners/**', UNIVERSAL],
    ['owners.yaml', UNIVERSAL],
    // Left universal: the quarantine list covers all three suites at once, and
    // playwright.quarantine.ts and replay-shared's jest.config.js read it
    // alongside pytest, so an entry for a flaky frontend test moves a
    // frontend lane.
    ['.test_quarantine.json', UNIVERSAL],
    // bin/ appears in the backend, frontend, and E2E path filters alike.
    ['bin/**', UNIVERSAL],
    ['patches/**', UNIVERSAL],
    // Holds the Depot-runner copies of the workflows and composite actions in
    // .github/, so it decides what runs for everyone the same way.
    ['.depot/**', UNIVERSAL],
    // Names the Depot project every container build and runner is billed and
    // cached against. rust/depot.json is deliberately not here: it configures
    // builds of that workspace only, and the rust rules below hold it to them.
    ['depot.json', UNIVERSAL],
    // The toolchain every suite runs inside. ci-python.yml gates on
    // .flox/env/manifest.toml for that reason.
    ['.flox/**', UNIVERSAL],
    // The environment every suite runs inside: hogli loads .env.development and
    // .env.services before starting anything, the sandbox image bakes the same
    // pair, and .envrc activates the flox environment above. The two .example
    // files ride along rather than earning a rule of their own.
    ['.env*', UNIVERSAL],
    // ClickHouse, Postgres, and Temporal configuration mounted by every
    // docker-compose file, so it defines the services all the suites test
    // against. The collector config is mounted the same way, from the root.
    ['docker/**', UNIVERSAL],
    ['otel-collector-config*.yaml', UNIVERSAL],
    // duckgres.yaml is mounted into the same stack, and intent-map.yaml steers
    // bin/sandbox and hogli, both already tripwires.
    ['devenv/**', UNIVERSAL],
    // Holds the markdownlint config, which is the same class of rule change,
    // and markdown is the one thing every tree has.
    ['.config/**', UNIVERSAL],
]

// Subdirectories of common/ that belong to a single domain. Anything else
// under common/ is deliberately absent so it falls through to ALL rather than
// being guessed at.
const COMMON_PYTHON = ['hogql_parser', 'hogvm', 'ingestion', 'migration_utils', 'plugin_transpiler', 'alerting']
const COMMON_FRONTEND = ['esbuilder', 'storybook', 'tailwind', 'replay-shared', 'replay-headless']

// Subdirectories of common/ that both language families read. Test data owned
// by neither: the ai-multimodal fixtures are loaded by a product's Playwright
// spec and recorded by a Python script sitting beside them.
const COMMON_FULLSTACK = ['fixtures']

// The pr-approval-agent engine's home inside the stamphog product.
const PR_APPROVAL_AGENT_DIR = 'products/stamphog/packages/pr-approval-agent'

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
    'query-performance-ai',
    'infra-scripts',
]

// Top-level trees that hold a lane instead of falling through to ALL, keyed by
// the first path segment, which is the directory for a tree and the file name
// for a file sitting at the repository root. Every entry names the suite that
// would catch a conflict in it, and a tree nobody has placed here still widens,
// so the list grows by decision rather than by default.
const STANDALONE_TREES = new Map([
    // The cargo-dist workspace, whose only member is cli/. It decides what the
    // released posthog-cli artifacts contain, and ci-cli.yml builds those from
    // services/mcp sources, so it takes the same pair cli/ does.
    ['dist-workspace.toml', ['cli', 'svc:mcp']],
    // A cargo workspace of its own (cli/Cargo.lock, outside rust/ and outside
    // the pnpm workspace). ci-cli.yml also builds it from services/mcp sources,
    // so the two trees have to share a lane.
    ['cli', ['cli', 'svc:mcp']],
    // Go service with its own CI. ci-hog.yml ignores livestream/** explicitly,
    // so its Hog implementation is not covered by the shared hog suite either.
    ['livestream', ['livestream']],
    // Another standalone cargo workspace, and nothing in the dev or CI stack
    // builds it: the UDF binary reaches ClickHouse through its image.
    ['funnel-udf', ['funnel-udf']],
    // Terragrunt definitions for dashboards and alerts. No suite compiles them,
    // and terragrunt-posthog.yaml is the only workflow that reads the tree.
    ['terraform', ['terraform']],
    // ci-python.yml validates the policy files through the pr-approval-agent
    // pytest suite, which already owns that lane.
    ['.stamphog', ['tools:pr-approval-agent']],
])

// Editor, IDE, and agent configuration. No suite reads any of it, so one shared
// lane between the lot costs nothing and keeps the inert set to files that
// genuinely compile into nothing. Two trees stay off both lists: agent-os/ and
// share/ hold only markdown today, which the prose rule already claims, and
// anything else appearing there should widen until someone classifies it.
//
// .posthog-code is the entry that looks like an exception and is not. The
// desktop app does parse .posthog-code/environments/*.toml, but it parses
// whichever repository a user opens, and EnvironmentService's suite writes its
// fixtures to a temp directory instead of reading this repository's copy. That
// suite also covers a file being invalid TOML or off-schema, both of which the
// service skips, so a config and a parser that disagree leave an environment
// unlisted rather than failing anything. No suite here would catch the pair, so
// sharing the desktop product's lane would serialize the two for no validation.
const REPO_CONFIG_DIRS = [
    '.claude',
    '.codex',
    '.cursor',
    '.dagster_home',
    '.greptile',
    '.husky',
    '.idea',
    '.interface-design',
    '.posthog-code',
    '.run',
    '.vscode',
    '.zed',
]

// The same class of file, one per root path rather than one per tree: the
// ignore and rule files belonging to the directories above, the VCS settings,
// the review bot's config, and the license. No suite reads any of them. The
// tools that do read them (direnv, watchman, the worktree helpers, the desktop
// MCP client) either run outside CI or are driven by bin/, which is universal
// and so overlaps this lane already.
//
// .dockerignore and the .env files are deliberately not here. Both are read by
// something that every suite runs inside, and both are tripwires above.
const REPO_CONFIG_FILES = [
    '.cursorignore',
    '.cursorrules',
    '.editorconfig',
    '.git-blame-ignore-revs',
    '.gitattributes',
    '.gitignore',
    '.mcp.json',
    '.watchmanconfig',
    '.worktreeinclude',
    '.worktreelink',
    'LICENSE',
]
for (const entry of [...REPO_CONFIG_DIRS, ...REPO_CONFIG_FILES]) {
    STANDALONE_TREES.set(entry, ['repo-config'])
}

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

const TRIPWIRE_MATCHERS = TRIPWIRE_RULES.map(([glob, domain]) => [globToRegExp(glob), domain])

// The domain of the first rule matching the file, or null when no rule claims
// it and when a rule claims it as an explicit non-tripwire. Both mean the same
// thing to every caller: the file falls through to the ordinary rules.
function tripwireDomain(file) {
    const matched = TRIPWIRE_MATCHERS.find(([re]) => re.test(file))
    return matched ? matched[1] : null
}

function isTripwire(file) {
    return tripwireDomain(file) !== null
}

// --- Semgrep rule languages ---

const SEMGREP_DIR = '.semgrep'

// Only languages whose lanes this script can name. `generic`, `yaml`, and the
// rest are deliberately absent so a rule using them widens.
const SEMGREP_LANGUAGE_DOMAINS = new Map([
    ['python', PYTHON],
    ['py', PYTHON],
    ['typescript', JAVASCRIPT],
    ['ts', JAVASCRIPT],
    ['javascript', JAVASCRIPT],
    ['js', JAVASCRIPT],
    ['tsx', JAVASCRIPT],
    ['jsx', JAVASCRIPT],
])

// Collects every `languages:` value in a rule file. Semgrep accepts the inline
// list and the block-sequence spellings, and a file holds many rules, so the
// result is the union across all of them.
function parseSemgrepLanguages(text) {
    const languages = new Set()
    const clean = (value) =>
        value
            .trim()
            .replace(/^['"]|['"]$/g, '')
            .toLowerCase()
    const lines = text.split('\n')
    for (let i = 0; i < lines.length; i++) {
        const declaration = lines[i].match(/^\s*languages:\s*(.*)$/)
        if (!declaration) {
            continue
        }
        const inline = declaration[1].replace(/#.*$/, '').trim()
        if (inline.startsWith('[')) {
            for (const language of inline.slice(1).split(']')[0].split(',')) {
                if (language.trim()) {
                    languages.add(clean(language))
                }
            }
            continue
        }
        if (inline) {
            languages.add(clean(inline))
            continue
        }
        for (let j = i + 1; j < lines.length; j++) {
            const item = lines[j].match(/^\s*-\s*(.+)$/)
            if (!item) {
                break
            }
            languages.add(clean(item[1].replace(/#.*$/, '')))
        }
    }
    return languages
}

// A rule file is held to one domain only when every language it declares maps
// to that same domain. No declaration, an unmapped language, or a rule spanning
// both sides yields universal.
function semgrepDomain(text) {
    const languages = parseSemgrepLanguages(text)
    if (languages.size === 0) {
        return UNIVERSAL
    }
    const domains = new Set()
    for (const language of languages) {
        const domain = SEMGREP_LANGUAGE_DOMAINS.get(language)
        if (!domain) {
            return UNIVERSAL
        }
        domains.add(domain)
    }
    return domains.size === 1 ? [...domains][0] : UNIVERSAL
}

function loadSemgrepDomains(repoRoot) {
    const domains = new Map()
    const walk = (dir) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, entry.name)
            if (entry.isDirectory()) {
                walk(full)
            } else if (/\.ya?ml$/.test(entry.name)) {
                const relative = path.relative(repoRoot, full).split(path.sep).join('/')
                domains.set(relative, semgrepDomain(fs.readFileSync(full, 'utf8')))
            }
        }
    }
    try {
        walk(path.join(repoRoot, SEMGREP_DIR))
    } catch (error) {
        console.error(`Semgrep rules unreadable (${error.message}); every rule change widens`)
    }
    return domains
}

// Tool caches share the directory with the products, so a local run can pick up
// directories such as .ruff_cache, .pytest_cache, and __pycache__ as products and
// invent a lane for each. CI never sees them because a fresh checkout has only
// tracked directories and this job does not run Python, so this keeps a local run
// consistent with CI rather than fixing a live miscount. Dropping a real product
// would only ever widen, because an unrecognized product name falls through to
// ALL, so the filter is safe in the one direction it can be wrong.
function isProductDirectory(name) {
    return !name.startsWith('.') && !name.startsWith('__') && name !== 'node_modules'
}

function listProducts(repoRoot) {
    return fs
        .readdirSync(path.join(repoRoot, 'products'), { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && isProductDirectory(entry.name))
        .map((entry) => entry.name)
        .sort()
}

// A product is isolated when it declares a backend:contract-check script *and*
// narrows that task's inputs in its own turbo.json, the same pair turbo-discover
// uses to decide a product can be tested alone. The script alone leaves the task
// on the root definition, whose inputs are the product's whole backend, so the
// product claims a contract surface it never narrowed. Non-isolated products
// have no narrowed contract, so a change in one is treated as a core change.
function listIsolatedProducts(repoRoot, products, contractSurfaces) {
    const isolated = new Set()
    for (const product of products) {
        const manifest = path.join(repoRoot, 'products', product, 'package.json')
        if (!fs.existsSync(manifest) || !contractSurfaces.has(product)) {
            continue
        }
        const parsed = JSON.parse(fs.readFileSync(manifest, 'utf8'))
        if (parsed.scripts && parsed.scripts['backend:contract-check']) {
            isolated.add(product)
        }
    }
    return isolated
}

// --- Nested JS workspaces ---

// A product that vendors its own pnpm workspace (products/desktop is the one
// today) has an apps/ + packages/ layout instead of the backend/ + frontend/
// split the product rules assume. Its manifests, configs, and assets are none
// of .py, backend/, or .tsx, so they land in the "could be either" bucket and
// widen to every backend lane, which is how a package.json under packages/
// serializes a TypeScript-only PR against all of Python.
//
// The workspace file is the product's own declaration of which subtrees are JS
// packages, so it is a safer signal than an extension allowlist: a path only
// narrows when the product itself says a JS package lives there. Anything
// outside those subtrees (the product's root manifests, scripts/, backend/)
// keeps the old widening behavior.
const WORKSPACE_DECLARATION = 'pnpm-workspace.yaml'

// pnpm's own two files at the product root. A pnpm-workspace.yaml makes that
// directory a workspace root rather than a member of the repo-root one, so the
// lockfile beside it resolves that workspace's packages and nothing else. The
// repo-root lockfile is a separate file and stays a tripwire in its own right.
// Neither of these is importable from Python, and neither is a contract
// declaration, so without this rule they fall through the layout checks below
// and claim every backend lane: a desktop dependency bump lands in the same
// lane as all of Python.
//
// The self-gating hazard that keeps CONTRACT_DECLARATIONS widening does not
// transfer here. turbo.json and package.json declare a Python import surface,
// so a PR that narrows one and edits under it in the same commit would gate
// itself against its own new contract. This pair declares no Python surface,
// and the .py carve-out below applies whatever the globs say.
const WORKSPACE_OWN_FILES = [WORKSPACE_DECLARATION, 'pnpm-lock.yaml']

// Minimal reader for the `packages:` block of a pnpm workspace file. Only the
// list-of-globs form is understood; anything else yields no globs, which leaves
// the product on the old behavior rather than guessing.
function parseWorkspacePackageGlobs(text) {
    const globs = []
    let inPackages = false
    for (const rawLine of text.split('\n')) {
        const line = rawLine.replace(/#.*$/, '').trimEnd()
        if (!line.trim()) {
            continue
        }
        if (/^packages:\s*$/.test(line)) {
            inPackages = true
            continue
        }
        if (!inPackages) {
            continue
        }
        const item = line.match(/^\s+-\s+(.+)$/)
        if (!item) {
            break
        }
        globs.push(item[1].trim().replace(/^['"]|['"]$/g, ''))
    }
    return globs
}

function compileWorkspaceMatcher(globs) {
    const include = []
    const exclude = []
    for (const glob of globs) {
        const negated = glob.startsWith('!')
        const matcher = globToRegExp(negated ? glob.slice(1) : glob)
        ;(negated ? exclude : include).push(matcher)
    }
    if (include.length === 0) {
        return null
    }
    // The globs name package directories, so a file is inside the workspace
    // when one of its ancestor directories matches. Testing the file path
    // itself would miss everything below the package root.
    return (relativePath) => {
        const segments = relativePath.split('/')
        for (let depth = 1; depth < segments.length; depth++) {
            const dir = segments.slice(0, depth).join('/')
            if (include.some((re) => re.test(dir)) && !exclude.some((re) => re.test(dir))) {
                return true
            }
        }
        return false
    }
}

function loadProductWorkspaces(repoRoot, products) {
    const workspaces = new Map()
    for (const product of products) {
        const declaration = path.join(repoRoot, 'products', product, WORKSPACE_DECLARATION)
        if (!fs.existsSync(declaration)) {
            continue
        }
        let matcher
        try {
            matcher = compileWorkspaceMatcher(parseWorkspacePackageGlobs(fs.readFileSync(declaration, 'utf8')))
        } catch (error) {
            console.error(
                `Could not read products/${product}/${WORKSPACE_DECLARATION} (${error.message}); its files keep widening to every backend lane`
            )
            continue
        }
        if (matcher) {
            workspaces.set(product, matcher)
        }
    }
    return workspaces
}

function isInProductWorkspace(product, file, productWorkspaces) {
    const matcher = productWorkspaces.get(product)
    if (!matcher) {
        return false
    }
    const relativePath = file.slice(`products/${product}/`.length)
    return WORKSPACE_OWN_FILES.includes(relativePath) || matcher(relativePath)
}

// --- Backend-detached products ---

// The narrowing above stops at the layout rules: a product with a vendored
// workspace still owns every backend lane the moment one of its files reads as
// backend, because the product rules assume every product is a Django product
// whose Python some other product may import. products/desktop is not one. It
// is a standalone app imported from another repository, with no manifest.tsx,
// no backend/, no entry in frontend/src/products.json, and its own desktop-*
// CI. The Python it does carry is a vendored copy of that repository's own
// tooling under tools/, which this repository's suites never load.
//
// Two enforced declarations say so, and both have to hold:
//
//   1. pytest.ini ignores the subtree, so no backend test collects a single
//      file under it. ci-backend.yml carries the same exclusion in its path
//      filter, but a filter tuned to over-run is not a safe source for lane
//      assignment, while an --ignore is a statement that the suite does not
//      cover the path at all.
//   2. The product is absent from tach.toml, the enforced Python module graph,
//      so no declared module may import it.
//
// A product satisfying both cannot fail another product's backend suite, so
// its files claim its own lanes instead of all of them. Either condition
// missing keeps the old widening, and so does an unreadable pytest.ini or an
// unavailable tach graph. Both declarations are already tripwires, so a PR
// that detaches a product cannot itself run beside anything.
const PYTEST_CONFIG = 'pytest.ini'

// Reads the --ignore paths out of pytest's addopts. Nothing matching yields an
// empty list, which leaves every product on the old widening.
function parsePytestIgnores(text) {
    return [...text.matchAll(/--ignore[= ](\S+)/g)].map((match) => match[1].replace(/\/+$/, ''))
}

function loadBackendDetachedProducts(repoRoot, products, tachGraph) {
    if (!tachGraph) {
        return new Set()
    }
    let ignored
    try {
        ignored = new Set(parsePytestIgnores(fs.readFileSync(path.join(repoRoot, PYTEST_CONFIG), 'utf8')))
    } catch (error) {
        console.error(`Could not read ${PYTEST_CONFIG} (${error.message}); every product widens to all backend lanes`)
        return new Set()
    }
    const detached = new Set()
    for (const product of products) {
        if (ignored.has(`products/${product}`) && !isTachDeclared(product, tachGraph)) {
            detached.add(product)
        }
    }
    return detached
}

// tach spells its modules both ways across the file, so a product counts as
// declared under either spelling. A product absent from the graph, or a graph
// that could not be read at all, is not constrained by `tach check` and so has
// no bounded importer set.
function isTachDeclared(product, tachGraph) {
    if (!tachGraph) {
        return false
    }
    return tachGraph.graph.has(product) || tachGraph.graph.has(product.replace(/_/g, '-'))
}

function listTachDeclaredProducts(products, tachGraph) {
    return new Set(products.filter((product) => isTachDeclared(product, tachGraph)))
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
    return (relativePath) => include.some((re) => re.test(relativePath)) && !exclude.some((re) => re.test(relativePath))
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

function isContractDeclaration(product, file) {
    return CONTRACT_DECLARATIONS.includes(file.slice(`products/${product}/`.length))
}

function touchesContractSurface(product, file, contractSurfaces) {
    const relativePath = file.slice(`products/${product}/`.length)
    if (isContractDeclaration(product, file)) {
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
                    // A package.json beside the Cargo.toml means the crate also
                    // builds an npm package, so its lane extends past rust/.
                    const publishesNpmPackage = fs.existsSync(path.join(dir, 'package.json'))
                    crates.push({ dir: relative, name, text, publishesNpmPackage })
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

// Dependencies no Cargo.toml declares, because they are not compile-time edges:
// the key crate spawns the listed ones as binaries at run time. The cargo graph
// cannot see that, so the reverse closure would stop short of the spawner and
// leave it free to merge in parallel with a change to a service it executes.
//
// Mirrors the [[package-rule]] on-affected block in
// rust/affected-services/determinator-rules.toml, which exists for this same
// blind spot on the CI side. The two lists have to be changed together, which a
// test asserts, and loadRustGraph gives up the whole graph rather than dropping
// an edge if a crate named here stops existing.
const RUNTIME_SPAWN_EDGES = new Map([
    [
        'personhog-test-harness',
        ['personhog-replica', 'personhog-router', 'personhog-leader', 'personhog-writer', 'personhog-identity'],
    ],
])

// Returns null when the crate graph can't be built. Callers must treat null as
// "unknown dependents" and widen to every target, never as "no dependents".
// Widening past the rust lanes is deliberate: without the graph the script
// cannot tell which crate a rust path belongs to either, so the rust targets
// alone would not be a superset of what the change can break.
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
        // A crate renamed out from under the runtime map would otherwise drop
        // its edge silently, which is the under-reporting direction, so an
        // unresolvable entry gives up the whole graph instead.
        for (const [spawner, spawned] of RUNTIME_SPAWN_EDGES) {
            const unknown = [spawner, ...spawned].filter((crate) => !crateNames.has(crate))
            if (unknown.length > 0) {
                console.error(
                    `Runtime spawn edges name crates that no longer exist (${unknown.join(', ')}); ` +
                        'widening to every target until RUNTIME_SPAWN_EDGES is updated'
                )
                return null
            }
            dependsOn.set(spawner, [...new Set([...dependsOn.get(spawner), ...spawned])])
        }
        const nativeBindings = new Set(crates.filter((crate) => crate.publishesNpmPackage).map((crate) => crate.name))
        // Longest directory first so rust/common/hogvm resolves to its own crate
        // rather than to rust/common.
        const byDir = crates
            .map((crate) => ({ dir: crate.dir, name: crate.name }))
            .sort((a, b) => b.dir.length - a.dir.length)
        return { dependsOn, byDir, nativeBindings }
    } catch (error) {
        console.error(`Rust crate graph unavailable (${error.message}); widening to every target`)
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

// The lanes that import a native module built from the cargo workspace.
// nodejs/package.json is the only dependent of the two binding packages
// (@posthog/hogvm-node, @posthog/replay-anonymizer) today,
// and the test suite re-derives that from pnpm-workspace.yaml so a second
// dependent fails there rather than silently going unclaimed here.
const NATIVE_BINDING_CONSUMER_LANES = ['node:ingestion']

// Every target this script can emit. A widening decision names this set instead
// of the "ALL" sentinel, so the set intersection Trunk computes is unchanged
// while the target list stays readable: the telemetry can show which lanes a
// widened PR claimed, and diffing that against the lanes it should have claimed
// is how a rule gets tuned. "ALL" survives only for the cases below where the
// set cannot be built at all, which is a different statement — not "everything"
// but "unknown".
//
// THE INVARIANT: every target computeTargets can produce has to appear here. A
// target missing from this set makes a widened PR disjoint from the PR that
// claims it, which is the one failure mode that silently breaks master. The
// dynamic parts (products, services, crates) are read rather than listed for
// that reason, and a missing one returns null so the caller falls back to ALL.
function allKnownTargets(context) {
    const { products, services, rustGraph } = context
    if (!rustGraph || !services) {
        return null
    }
    const targets = new Set(['py:core', 'fe:core', 'node:ingestion', 'agents'])
    for (const product of products) {
        targets.add(pyProduct(product))
        targets.add(feProduct(product))
    }
    for (const service of services) {
        targets.add(`svc:${service}`)
    }
    for (const tool of TOOLS_INDEPENDENT) {
        targets.add(`tools:${tool}`)
    }
    for (const entries of STANDALONE_TREES.values()) {
        for (const target of entries) {
            targets.add(target)
        }
    }
    for (const crate of rustGraph.dependsOn.keys()) {
        targets.add(rustCrate(crate))
    }
    // "ALL" overlapped the prose lane too, so a docs PR serialized behind a
    // lockfile bump. Keeping prose here preserves that exactly rather than
    // smuggling a narrowing into a change that is meant to be a rename.
    targets.add('prose')
    return [...targets].sort()
}

function everything(context) {
    return allKnownTargets(context) || ALL
}

// The lanes a tripwire domain claims. Each is a superset of what a file in that
// domain can break, and each returns false when it cannot name its lanes in
// full, which sends the caller to the universal set rather than to a partial
// one.
function addPythonLanes(targets, context) {
    targets.add('py:core')
    for (const product of context.products) {
        targets.add(pyProduct(product))
    }
    // pyproject.toml roots products, but Python also lives under tools/, and the
    // pr-approval-agent engine holds a lane of its own through .stamphog.
    for (const tool of TOOLS_INDEPENDENT) {
        targets.add(`tools:${tool}`)
    }
    targets.add('tools:pr-approval-agent')
    return true
}

function addJavaScriptLanes(targets, context) {
    if (!context.services) {
        return false
    }
    targets.add('fe:core')
    for (const product of context.products) {
        targets.add(feProduct(product))
    }
    // The pnpm workspace spans frontend, nodejs, services, tools, and products,
    // and ci-cli.yml builds the CLI from services/mcp sources.
    targets.add('node:ingestion')
    for (const service of context.services) {
        targets.add(`svc:${service}`)
    }
    for (const tool of TOOLS_INDEPENDENT) {
        targets.add(`tools:${tool}`)
    }
    targets.add('cli')
    targets.add('svc:mcp')
    return true
}

// Both lane families in full, plus the MCP pair. The frontend half cannot be
// narrowed to the product that owns the manifest: every manifest's urls and
// tree items are merged into one global object, so any product's frontend can
// reference what another's manifest declares.
//
// services/mcp/scripts reads the manifests directly — lint-tool-names.ts walks
// products/*/manifest.tsx for the routes the generated app-url manifest cannot
// carry — so svc:mcp is a reader like any other, and ci-cli.yml builds the CLI
// from those same sources.
//
// The Python half is spelled out rather than delegated to addPythonLanes, which
// also claims the independent tools/ lanes. Those exist because the Python
// toolchain spans tools/, and no tool in that list loads products.json or globs
// the manifests.
//
// `query-schema` reaches the same set through different readers, so it shares
// this function while keeping its own domain name for the telemetry.
function addProductSurfaceLanes(targets, context) {
    targets.add('py:core')
    targets.add('fe:core')
    for (const product of context.products) {
        targets.add(pyProduct(product))
        targets.add(feProduct(product))
    }
    targets.add('svc:mcp')
    targets.add('cli')
    return true
}

function addRustLanes(targets, context) {
    if (!context.rustGraph) {
        return false
    }
    for (const crate of context.rustGraph.dependsOn.keys()) {
        targets.add(rustCrate(crate))
    }
    return true
}

// The crates the determinator says the change set moved, or every crate when it
// could not say. computeTargets runs its reverse closure over whatever lands
// here, so these are seeds rather than a finished answer.
//
// An answer naming no crate is a real verdict on a lockfile edit that moved no
// resolution, but claiming nothing for it costs more than it saves. A change set
// of only rust/Cargo.lock would then reach computeTargets' empty-set guard,
// which reads a target-less set as a path no rule claimed and widens to every
// lane in the repo — worse than the every-crate fallback, for a case rare enough
// not to be worth the lanes.
function addCargoLockLanes(targets, context) {
    const crates = context.cargoLockCrates
    if (!crates || crates.length === 0) {
        return addRustLanes(targets, context)
    }
    for (const crate of crates) {
        targets.add(rustCrate(crate))
    }
    return true
}

// The nodejs lane on its own. No tripwire resolves to it, because a file that
// can break the ingestion suite can almost always break more than that. The
// rust and proto rules still need to name it without dragging in the frontend.
const NODE = 'node'

function addNodeLanes(targets) {
    targets.add('node:ingestion')
    return true
}

// Each proto tree and the consumers that generate from it. proto/README.md's
// consumer table is the source, and the generated code is the check on it: a
// consumer that read a proto without committing stubs would be reading nothing.
// A test re-derives both halves from the tree — the crate from the build.rs
// that compiles the tree, the stub directories from disk — so a renamed crate
// or a fourth consumer fails there rather than going unclaimed here.
//
// The rust half names the crate that compiles the tree rather than every crate.
// tonic turns the tree into that crate's generated module and nothing else, so
// the crates a proto change can break are the ones that depend on it, which is
// the reverse closure computeTargets already runs over every rust:crate: target
// it holds. That is the same treatment a file inside the crate would get.
//
// The nodejs half takes the node domain rather than the javascript one because
// the stubs land only in nodejs/src/common/generated; no frontend or services
// package imports them. The python half cannot narrow below every python lane:
// the stubs are checked into posthog/, which is py:core, and py:core covers
// every product lane by construction.
// stubDir names the checked-in stub directory when it differs from the tree
// name; the consistency test reads it. ingestion's node stubs land in
// nodejs/src/common/generated/ingestion-worker, not .../ingestion.
const PROTO_TREES = new Map([
    ['cymbal', { crates: ['cymbal-proto'], domains: [] }],
    ['ingestion', { crates: ['ingestion-worker-proto'], domains: [NODE], stubDir: 'ingestion-worker' }],
    ['kafka_assigner', { crates: ['kafka-assigner-proto'], domains: [] }],
    ['personhog', { crates: ['personhog-proto'], domains: [PYTHON, NODE] }],
    ['prometheus', { crates: ['prometheus-rw-proto'], domains: [] }],
    ['usage_ingestion', { crates: ['usage-ingestion-proto'], domains: [NODE], stubDir: 'usage-ingestion' }],
])

// A file directly under proto/ is treated as impacting all trees, since it's not
// scoped to a single proto subdirectory. A subdirectory the table does not name
// has unknown consumers and widens, which is what makes adding a tree without
// declaring it here safe rather than silent.
function addProtoLanes(targets, context, file) {
    const segments = file.split('/')
    const trees =
        segments.length === 2 ? [...PROTO_TREES.keys()] : [segments[1]].filter((tree) => PROTO_TREES.has(tree))
    if (trees.length === 0 || !context.rustGraph) {
        return false
    }
    for (const tree of trees) {
        const { crates, domains } = PROTO_TREES.get(tree)
        // A crate renamed out from under the table would drop the rust half
        // silently, which is the under-reporting direction.
        if (crates.some((crate) => !context.rustGraph.dependsOn.has(crate))) {
            console.error(
                `No crate named for proto tree ${tree}; widening to every target until PROTO_TREES is updated`
            )
            return false
        }
        for (const crate of crates) {
            targets.add(rustCrate(crate))
        }
        for (const domain of domains) {
            if (!DOMAIN_LANES.get(domain)(targets, context)) {
                return false
            }
        }
    }
    return true
}

const DOMAIN_LANES = new Map([
    [PYTHON, addPythonLanes],
    [JAVASCRIPT, addJavaScriptLanes],
    [RUST, addRustLanes],
    [CARGO_LOCK, addCargoLockLanes],
    [NODE, addNodeLanes],
    [PRODUCT_SURFACE, addProductSurfaceLanes],
    [PROTO, addProtoLanes],
])

// Returns false when the file's domain is universal, which is the caller's cue
// to abandon the per-file accumulation and report the whole set.
function applyTripwireDomain(domain, file, targets, context) {
    const resolved = domain === SEMGREP ? (context.semgrepDomains || new Map()).get(file) || UNIVERSAL : domain
    const addLanes = DOMAIN_LANES.get(resolved)
    return addLanes ? addLanes(targets, context, file) : false
}

// Paths under rust/ that belong to no crate, and the domains that read them. A
// crate directory answers for itself; these do not, so each entry is a decision
// and a subdirectory nobody has placed here still widens.
const RUST_NON_CRATE_RULES = [
    // posthog/conftest.py replays these files to build the persons database
    // every backend test runs against, so the schema they declare is Python's
    // as much as it is Rust's.
    ['rust/persons_migrations/', [RUST, PYTHON]],
    // The cyclotron tables the nodejs CDP consumers read and write.
    ['rust/cyclotron-node-migrations/', [RUST, NODE]],
    ['rust/behavioral_cohorts_migrations/', [RUST]],
    ['rust/flags_read_store_migrations/', [RUST]],
    // The entrypoints of the sqlx-migrate image, which applies every set above.
    // rust/affected-services declares the same grouping in
    // NON_CRATE_IMAGE_TRIGGERS, and this list has to stay a superset of it.
    ['rust/bin/', [RUST, PYTHON, NODE]],
    // Cargo and nextest settings: every crate compiles and tests under them.
    ['rust/.cargo/', [RUST]],
    ['rust/.config/', [RUST]],
]

// A file sitting directly at rust/ configures the cargo workspace itself (the
// Dockerfiles its images build from, the compose stack, the dotfiles, the
// license), so the crates are its readers. That reasoning does not extend to a
// subdirectory, which could hold anything, so one the rules above do not name
// returns false and widens.
function applyRustNonCrateLanes(file, targets, context) {
    const rule = RUST_NON_CRATE_RULES.find(([prefix]) => file.startsWith(prefix))
    const isWorkspaceRoot = file.split('/').length === 2
    if (!rule && !isWorkspaceRoot) {
        return false
    }
    const domains = rule ? rule[1] : [RUST]
    return domains.every((domain) => DOMAIN_LANES.get(domain)(targets, context))
}

function computeTargets(changedFiles, context) {
    const {
        products,
        isolatedProducts,
        rustGraph,
        tachGraph,
        contractSurfaces = new Map(),
        productWorkspaces = new Map(),
        backendDetachedProducts = new Set(),
        tachDeclaredProducts = listTachDeclaredProducts(products, tachGraph),
    } = context
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

    const cascadeSeeds = new Set()
    let inertFiles = 0

    for (const file of changedFiles) {
        const tripwire = tripwireDomain(file)
        if (tripwire) {
            if (!applyTripwireDomain(tripwire, file, targets, context)) {
                return everything(context)
            }
            continue
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
        // zips products/*/skills/*, ci-agent-skills.yml gates on those paths and
        // on .agents/, and ci-python.yml runs the pr-approval-agent suite over
        // .stamphog/. All of them fall through to their directory rules below.
        const isBuildInput =
            top === '.agents' || top === '.stamphog' || (top === 'products' && segments[2] === 'skills')

        // The same suite reads every AGENT_APPROVALS.md wherever it sits, so the
        // file belongs to that lane rather than to the tree holding it. On the
        // product lane its own directory rule would give it, a policy change and
        // a parser change would be free to merge in parallel.
        if (segments[segments.length - 1] === 'AGENT_APPROVALS.md') {
            targets.add('tools:pr-approval-agent')
            continue
        }
        // The engine sits inside the stamphog product, but no product suite imports it. ci-python
        // runs its tests directly, and those are the same tests that .stamphog/ and every
        // AGENT_APPROVALS.md feed into. All three share one lane, so a policy change and an engine
        // change cannot merge in parallel against each other.
        if (file.startsWith(`${PR_APPROVAL_AGENT_DIR}/`)) {
            targets.add('tools:pr-approval-agent')
            continue
        }
        if (/\.mdx?$/.test(file) && !isBuildInput) {
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
        const standalone = STANDALONE_TREES.get(top)
        if (standalone) {
            for (const target of standalone) {
                targets.add(target)
            }
            continue
        }
        if (top === 'tools') {
            // A file sitting directly under tools/ rather than inside a tool's
            // own directory is one of the CI-steering scripts (backend test
            // selection, playwright spec selection, the selection verdict).
            // Those decide what runs across every suite, so they widen fully.
            if (segments.length < 3) {
                return everything(context)
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
            // A file at the root of common/ is the tree's own package marker,
            // shared by whichever subdirectories import it, so it takes both
            // families rather than guessing at one.
            if (segments.length === 2 || COMMON_FULLSTACK.includes(segments[1])) {
                allPyProducts()
                allFeProducts()
                continue
            }
            return everything(context)
        }
        if (top === 'rust') {
            if (!rustGraph) {
                targets.add('rust:unresolved')
                continue
            }
            const crate = rustGraph.byDir.find(
                (entry) => file.startsWith(`rust/${entry.dir}/`) || file === `rust/${entry.dir}`
            )
            if (crate) {
                targets.add(rustCrate(crate.name))
                continue
            }
            if (!applyRustNonCrateLanes(file, targets, context)) {
                return everything(context)
            }
            continue
        }
        // A file at the root of products/ is shared by all of them: the package
        // marker, the conftest every product's tests collect, the database
        // routing map, the lint config. It cannot be held to one product, and
        // nothing outside the two language families reads any of it.
        if (top === 'products' && segments.length === 2) {
            allPyProducts()
            allFeProducts()
            continue
        }
        if (top === 'products' && segments.length > 2) {
            const product = segments[1]
            if (!products.includes(product)) {
                return everything(context)
            }
            const isBackend = segments[2] === 'backend' || file.endsWith('.py')
            const isFrontend = segments[2] === 'frontend' || /\.tsx?$/.test(file)
            // Only reached for a file that is neither, and only inside a
            // package the product's own pnpm workspace declares. A .py there
            // is still backend: the workspace says the directory holds a JS
            // package, not that Python cannot be checked into it.
            const isWorkspaceOnly = !isBackend && !isFrontend && isInProductWorkspace(product, file, productWorkspaces)
            // Markdown reaches this branch only as a product skill, which the
            // prose rule exempts above because the skill build and the
            // product's own backend read those files. Both readers are Python,
            // so it takes the backend half of the "neither" default below and
            // not the frontend one: no frontend suite reads a skill.
            const isMarkdown = /\.mdx?$/.test(file)

            if (isFrontend || (!isBackend && !isFrontend && !isMarkdown)) {
                targets.add(feProduct(product))
            }
            if (isBackend || (!isBackend && !isFrontend && !isWorkspaceOnly)) {
                if (isolatedProducts.has(product)) {
                    targets.add(pyProduct(product))
                    if (touchesContractSurface(product, file, contractSurfaces)) {
                        cascadeSeeds.add(product)
                    }
                } else if (backendDetachedProducts.has(product)) {
                    // No backend suite covers this product and no declared
                    // module imports it, so the lane it keeps is its own. This
                    // case comes first because it also answers the declaration
                    // case below: a product absent from the module graph has no
                    // importers for the cascade to name.
                    targets.add(pyProduct(product))
                } else if (isContractDeclaration(product, file) || tachDeclaredProducts.has(product)) {
                    // A non-isolated product has declared no contract surface,
                    // so every backend file in it counts as contract and seeds
                    // the cascade. That names its direct importers, which is
                    // what a lane needs.
                    //
                    // Isolation is a stronger claim than this one and is not
                    // required here. It says a change inside the product can
                    // only break the product's own tests, which lets CI skip
                    // the full Django suite, and products/architecture.md is
                    // explicit that tach cannot prove it: cross-cutting tests
                    // reach a product's endpoints by URL, in process, with no
                    // import to see. A lane only has to answer whether another
                    // PR can reference the symbols this one changed, and that
                    // is the import half, which `tach check` does enforce. So a
                    // product can be too unsealed to skip the suite and still
                    // have a bounded importer set.
                    //
                    // The bound only holds for a product tach declares. One
                    // absent from the graph is unconstrained by `tach check`,
                    // so anything may import it and it still widens below.
                    targets.add(pyProduct(product))
                    cascadeSeeds.add(product)
                } else {
                    allPyProducts()
                }
            }
            continue
        }

        // Nothing claimed this path. Defaulting to an empty target set would
        // read as "parallel with everything", which is the one failure mode
        // that silently breaks master, so claim every lane instead.
        return everything(context)
    }

    // Naming a dependent's target is all a lane needs: it puts the two PRs in
    // the same lane so they are tested together. Isolation governs whether a
    // product's own change can be tested alone, which is a different question,
    // so a non-isolated dependent is named here rather than widening to every
    // backend target. Only 14 of the products declare a contract check, so
    // widening on each of them would collapse every cascade to the full set.
    //
    // The seeds are the products whose contract surface changed, plus any
    // product whose own declarations changed, and the dependents are one hop
    // deep. See the two numbered narrowings at the top of this file for what
    // that gives up.
    if (cascadeSeeds.size > 0) {
        const dependents = tachDependentProducts([...cascadeSeeds], tachGraph)
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
        const affectedCrates = reverseClosure(seeds, rustGraph.dependsOn)
        for (const crate of affectedCrates) {
            targets.add(rustCrate(crate))
        }
        // A crate that also builds an npm package compiles into a native module
        // the JS workspace imports, so the closure does not end at rust/. The
        // dependents are found through package.json rather than Cargo.toml,
        // which is why the crate graph alone stops one edge short.
        const bindings = rustGraph.nativeBindings || new Set()
        if (affectedCrates.some((crate) => bindings.has(crate))) {
            for (const target of NATIVE_BINDING_CONSUMER_LANES) {
                targets.add(target)
            }
        }
    }

    if (targets.has('rust:unresolved')) {
        targets.delete('rust:unresolved')
        if (rustGraph) {
            for (const crate of rustGraph.dependsOn.keys()) {
                targets.add(rustCrate(crate))
            }
        } else {
            return everything(context)
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
        // still widens.
        return inertFiles === changedFiles.length ? ['prose'] : everything(context)
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

// Every directory under services/ holds a lane, so the list has to be read
// rather than declared or allKnownTargets would miss a newly added one. Null on
// failure, which widens to the "ALL" sentinel instead of to a partial set.
function listServices(repoRoot) {
    try {
        return fs
            .readdirSync(path.join(repoRoot, 'services'), { withFileTypes: true })
            .filter((entry) => entry.isDirectory() && isProductDirectory(entry.name))
            .map((entry) => entry.name)
            .sort()
    } catch (error) {
        console.error(`Could not list services/ (${error.message}); widening decisions fall back to ALL`)
        return null
    }
}

// The crate list rust-compute-affected produced for this diff, as a JSON array.
// The workflow only runs the determinator when the change set holds
// rust/Cargo.lock, so on every other PR this is unset and never read.
const CARGO_LOCK_CRATES_ENV = 'CARGO_LOCK_CRATES'

// Returns null for unknown, which the caller widens on. The determinator answers
// for the whole diff rather than for the lockfile alone, so this is a superset
// of the lockfile's own contribution — the safe direction, and the union with
// the path rules is what lands either way.
//
// A name the crate graph does not know means the two disagree about the
// workspace, and a disagreement resolves to unknown rather than to a lane list
// built from half of it.
function parseCargoLockCrates(raw, rustGraph) {
    if (!rustGraph || !raw) {
        return null
    }
    let crates
    try {
        crates = JSON.parse(raw)
    } catch (error) {
        console.error(`${CARGO_LOCK_CRATES_ENV} is not JSON (${error.message}); a lockfile change claims every crate`)
        return null
    }
    if (!Array.isArray(crates) || crates.some((crate) => typeof crate !== 'string')) {
        console.error(`${CARGO_LOCK_CRATES_ENV} is not a list of crate names; a lockfile change claims every crate`)
        return null
    }
    const unknown = crates.filter((crate) => !rustGraph.dependsOn.has(crate))
    if (unknown.length > 0) {
        console.error(
            `The determinator named crates the graph does not hold (${unknown.join(', ')}); ` +
                'a lockfile change claims every crate'
        )
        return null
    }
    return crates
}

function buildContext(repoRoot) {
    const products = listProducts(repoRoot)
    const tachGraph = loadTachGraph(repoRoot)
    const rustGraph = loadRustGraph(repoRoot)
    const contractSurfaces = loadContractSurfaces(repoRoot, products)
    return {
        products,
        cargoLockCrates: parseCargoLockCrates(process.env[CARGO_LOCK_CRATES_ENV], rustGraph),
        services: listServices(repoRoot),
        isolatedProducts: listIsolatedProducts(repoRoot, products, contractSurfaces),
        contractSurfaces,
        productWorkspaces: loadProductWorkspaces(repoRoot, products),
        backendDetachedProducts: loadBackendDetachedProducts(repoRoot, products, tachGraph),
        tachDeclaredProducts: listTachDeclaredProducts(products, tachGraph),
        semgrepDomains: loadSemgrepDomains(repoRoot),
        rustGraph,
        tachGraph,
    }
}

module.exports = {
    computeTargets,
    allKnownTargets,
    buildContext,
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
    stripJsonComments,
    tripwireDomain,
    parseCargoLockCrates,
    ALL,
    CARGO_LOCK,
    JAVASCRIPT,
    NATIVE_BINDING_CONSUMER_LANES,
    NODE,
    PROTO_TREES,
    PYTHON,
    REPO_ROOT,
    RUNTIME_SPAWN_EDGES,
    RUST,
    UNIVERSAL,
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
