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
// be built at all — an unreadable crate inventory or services/ listing here, and a
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
//      than every backend lane. The tach map is the real Python import graph
//      (`tach map` reads the imports that `tach check` enforces in CI), so for
//      a product it walked, the products that import it are known from the
//      files. A product absent from that map has no known importer set and
//      still widens.
//
//      ACCEPTED RISK: the map is read from each PR's own tree, so an importer
//      that does not exist yet is not in it. PR A renames a symbol in X, PR B
//      adds the first call from Y to X, and neither lane names the other's
//      product; master holds the combination untested. The declared graph in
//      tach.toml covered only the slice of this where Y had listed X in
//      `depends_on` before importing it, and closing it fully would make every
//      PR claim what its products import as well, which lands nearly every
//      product PR in the hub products' lanes.
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
//      the product graph means every member reaches every other, so any seed inside it
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
// Its own domain because the file names no crate directory to seed from, so
// its radius is whatever the determinator's answer says the resolution change
// moved, degrading to every crate when that answer is absent.
const CARGO_LOCK = 'cargo-lock'

// The nodejs lane on its own, for files whose only reader is the ingestion
// suite or an image built purely from nodejs/ sources. The rust and proto
// rules also use it to name that lane without dragging in the frontend.
const NODE = 'node'

// Suites that run the backend and the frontend together: E2E, Hog, and the
// builds of the images those suites run inside. Both language families in
// full, which still leaves the rust crates and the standalone trees free
// (E2E runs prebuilt capture containers from rust/, but rust/** is outside
// its paths filter, so that gap is the filter's, not this lane's).
const FULLSTACK = 'fullstack'

// Release and CD workflows. See addDeployLane for why one shared lane is safe.
const DEPLOY = 'deploy'

// The hobby deployment: its install scripts and the smoke test that runs them.
const HOBBY = 'hobby'

// The desktop product's own CI and release workflows.
const DESKTOP = 'desktop'

// ci-cli.yml and the reusable cargo-dist plan it calls, which build the CLI
// from services/mcp sources. The same pair STANDALONE_TREES gives cli/ itself.
const CLI_ARTIFACTS = 'cli-artifacts'

// The hogbox preview-environment workflows, which read the hogbox tooling.
const HOGBOX_PREVIEW = 'hogbox-preview'

// Bot, report, sync, and canary workflows plus the scripts they run. None of
// them is a required check, so a break costs a bot action rather than a merge
// gate, and one shared lane keeps a script and the workflow that runs it
// serialized against each other.
const REPO_AUTOMATION = 'repo-automation'

// The local development stack: hogli start, the mprocs process lists, the
// readiness checks, and the developer-only helper scripts. No required check
// runs any of it except its own selftest workflows, which share the lane.
const DEV_ENV = 'dev-env'

// Entrypoints and configuration baked into the unified app image, which backs
// the E2E suites, the hobby deployment, and production alike.
const APP_IMAGE = 'app-image'

// Suites that gate documentation changes, which claim the prose lane. Their
// tooling has to share it, or a docs-check change and the docs PR it breaks
// against merge in parallel.
const PROSE_SUITE = 'prose-suite'

// The ownership data and the suite that validates it. No other suite's outcome
// depends on ownership jointly with a second PR's changes: the root owners.yaml
// is a fallback, so nothing can become unowned, and the readers outside the
// validation suite are review-routing bots. Two ownership edits can conflict
// with each other (a team renamed under a reference), which one shared lane
// serializes. A product's own owners.yaml keeps its product lane.
const OWNERSHIP = 'ownership'

// The vendored paths-filter action and its CI. It decides which jobs run
// inside a single run's own diff, so no run's outcome depends on it jointly
// with another queue entry: parallel entries never share a run, and master
// pushes skip the filters and run the suites in full. Its own tests pair with
// it in the lane.
const CI_TOOLING = 'ci-tooling'

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

    // tach.toml shapes one of those graphs (its exclude list decides what
    // `tach map` walks), so it carries the same self-gating hazard, but every
    // edge it can move lands on a python lane: `tach check` runs in
    // ci-backend.yml, and the two readers of the map, this script and
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
    // These two gate suites that run only Python: the tools and
    // approval-agent pytest suites, and the ClickHouse multinode migration
    // smoke.
    ['.github/workflows/ci-python.yml', PYTHON],
    ['.github/workflows/ci-clickhouse-multinode-migrations.yml', PYTHON],
    // Blocks Django or sqlx migrations landing beside nodejs/ or other rust/
    // changes, so all three families interact with an edit to the gate.
    ['.github/workflows/ci-migrations-service-separation-check.yml', [PYTHON, NODE, RUST]],
    // Suites that run the backend and the frontend together, and the builds of
    // the images those suites run inside. cd-sandbox-base-image is here rather
    // than on the deploy lane because it builds on pull requests from product
    // code, so it is a PR suite despite the cd- name, and it has to precede
    // the cd-*-image rule below.
    ['.github/workflows/ci-e2e-playwright.yml', FULLSTACK],
    ['.github/workflows/ci-e2e-playwright-audit.yml', FULLSTACK],
    ['.github/workflows/ci-hog.yml', FULLSTACK],
    ['.github/workflows/container-images-ci.yml', FULLSTACK],
    ['.github/workflows/cd-sandbox-base-image.yml', FULLSTACK],
    ['.github/workflows/ci-recording-rasterizer-container.yml', FULLSTACK],
    // The ml-mirror-image-scrub sidecar is built from nodejs/ sources only.
    ['.github/workflows/ci-ml-mirror-image-scrub-container.yml', NODE],
    // The skills build renders templates that import product Python, and the
    // embedded-payload job runs the services/mcp generator that writes into
    // products/*/frontend/generated/. It does not gate .agents/.
    ['.github/workflows/ci-agent-skills.yml', [PYTHON, JAVASCRIPT]],
    // buf lint and the stub drift checks span every proto tree, which is the
    // radius proto/buf.yaml gets.
    ['.github/workflows/ci-proto.yml', PROTO],
    // Suites owned by one service directory.
    ['.github/workflows/ci-llm-gateway.yml', 'service:llm-gateway'],
    ['.github/workflows/ci-oauth-proxy.yml', 'service:oauth-proxy'],
    ['.github/workflows/ci-agent-proxy.yml', 'service:agent-proxy'],
    // The UI apps build reads services/mcp and every products/*/mcp tree,
    // which are the readers the product-surface domain already names.
    ['.github/workflows/ci-mcp-ui-apps.yml', PRODUCT_SURFACE],
    ['.github/workflows/ci-cli.yml', CLI_ARTIFACTS],
    ['.github/workflows/release.yml', CLI_ARTIFACTS],
    // The hobby smoke test and the installer CI are the only suites that read
    // the hobby scripts, so they share the hobby lane with them (the bin/
    // rules below).
    ['.github/workflows/ci-hobby.yml', HOBBY],
    ['.github/workflows/ci-hobby-installer.yml', HOBBY],
    // The desktop product's whole CI and release family builds and tests only
    // products/desktop.
    ['.github/workflows/desktop-*.yml', DESKTOP],
    // Release and CD workflows: they publish artifacts from master pushes,
    // tags, or opt-in labels, and none of them is a required check on a pull
    // request or in the merge queue. See addDeployLane.
    ['.github/workflows/container-images-cd.yml', DEPLOY],
    ['.github/workflows/cd-*-image.yml', DEPLOY],
    ['.github/workflows/rust-docker-build.yml', DEPLOY],
    ['.github/workflows/release-cli.yml', DEPLOY],
    ['.github/workflows/publish-hogli.yml', DEPLOY],
    // Also read by rust-compute-affected in ci-rust and ci-nodejs, so it takes
    // the rust lanes on top of deploy: those PR checks parse it, even though
    // only the image builds act on what it maps.
    ['.github/rust-images.yml', [RUST, DEPLOY]],
    // The hogbox preview environment gates no check, and its deploys read the
    // hogbox tooling, which owns a lane already.
    ['.github/workflows/hogbox-preview-env.yml', HOGBOX_PREVIEW],
    ['.github/workflows/hogbox-preview-cleanup.yml', HOGBOX_PREVIEW],
    // CI scripts held to the workflows that run them: the backend test-timing
    // pair and the IDOR coverage check run only in ci-backend and its timing
    // workflow, while report_test_timings is read by the backend, frontend,
    // and nodejs workflows alike.
    ['.github/scripts/optimize_test_durations.py', PYTHON],
    ['.github/scripts/test_optimize_test_durations.py', PYTHON],
    ['.github/scripts/check-idor-model-coverage.py', PYTHON],
    ['.github/scripts/report_test_timings.py', FULLSTACK],
    ['.github/scripts/test_report_test_timings.py', FULLSTACK],
    // Bot, report, sync, and canary workflows. None is a required check; each
    // failure costs a bot action, a Slack post, or a canary signal. Their
    // scripts and config sit on the same lane further down.
    ['.github/workflows/auto-assign-labels.yml', REPO_AUTOMATION],
    ['.github/workflows/auto-assign-reviewers.yml', REPO_AUTOMATION],
    ['.github/workflows/browserslist.yml', REPO_AUTOMATION],
    ['.github/workflows/canary-flags-enable.yml', REPO_AUTOMATION],
    ['.github/workflows/ci-alerts-devex.yml', REPO_AUTOMATION],
    ['.github/workflows/ci-geoip-canary.yml', REPO_AUTOMATION],
    ['.github/workflows/ci-master-run-traces.yml', REPO_AUTOMATION],
    ['.github/workflows/eng-analytics-weekly-digest.yml', REPO_AUTOMATION],
    ['.github/workflows/foss-sync.yml', REPO_AUTOMATION],
    ['.github/workflows/inkeep-agent.yml', REPO_AUTOMATION],
    ['.github/workflows/monitor-github-rate-limit.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-autoresolve-conflicts.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-cleanup.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-closed.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-opened.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-posthog-js-reviewer.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-priority-review.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-resolve-outdated-bot-comments.yml', REPO_AUTOMATION],
    ['.github/workflows/pr-updated.yml', REPO_AUTOMATION],
    ['.github/workflows/private-sync.yml', REPO_AUTOMATION],
    ['.github/workflows/review-hog.yml', REPO_AUTOMATION],
    ['.github/workflows/stale.yaml', REPO_AUTOMATION],
    ['.github/workflows/test-quarantine.yml', REPO_AUTOMATION],
    ['.github/workflows/update-ai-costs.yml', REPO_AUTOMATION],
    ['.github/workflows/update-bot-ips.yml', REPO_AUTOMATION],
    ['.github/workflows/weekly-flaky-report.yml', REPO_AUTOMATION],
    ['.github/workflows/weekly-slow-tests-report.yml', REPO_AUTOMATION],
    // More single-suite workflows, held to the trees their suites read: the AI
    // evals, replay-vision evals, and ClickHouse HCL checks are Python; the
    // hogql parser builds wheels (python), an npm package (both families), and
    // a crate (rust); deltalite spans its crates and the wheel's python
    // consumers.
    ['.github/workflows/ci-ai.yml', PYTHON],
    ['.github/workflows/ci-replay-vision-evals.yml', PYTHON],
    ['.github/workflows/ci-clickhouse-hcl-schema.yml', PYTHON],
    ['.github/workflows/build-hogql-parser.yml', PYTHON],
    ['.github/workflows/build-hogql-parser-npm.yml', FULLSTACK],
    ['.github/workflows/build-hogql-parser-rs.yml', RUST],
    ['.github/workflows/rust-smoke-test-build.yml', RUST],
    ['.github/workflows/publish-replay-anonymizer-crate.yml', RUST],
    ['.github/workflows/build-deltalite.yml', [RUST, PYTHON]],
    ['.github/workflows/ci-deltalite-python.yml', [RUST, PYTHON]],
    // Standalone trees whose suites already own a lane.
    ['.github/workflows/build-livestream-tui.yml', 'livestream-suite'],
    ['.github/workflows/ci-livestream.yml', 'livestream-suite'],
    ['.github/workflows/ci-livestream-tui.yml', 'livestream-suite'],
    ['.github/workflows/livestream-docker-image.yml', 'livestream-suite'],
    ['.github/workflows/build-phrocs.yml', 'phrocs-suite'],
    ['.github/workflows/ci-phrocs.yml', 'phrocs-suite'],
    ['.github/workflows/terragrunt-posthog.yaml', 'terraform-suite'],
    ['.github/workflows/build-hobby-installer.yml', HOBBY],
    ['.github/workflows/ci-integration-service.yml', 'service:integration-service'],
    ['.github/workflows/ci-openapi-codegen.yml', PRODUCT_SURFACE],
    // Publish and CD workflows found after the first deploy pass.
    ['.github/workflows/llm-gateway-cd.yml', DEPLOY],
    ['.github/workflows/publish-quill-npm.yml', DEPLOY],
    ['.github/workflows/publish-symbol-data-crate.yml', DEPLOY],
    ['.github/workflows/clickhouse-udfs.yml', DEPLOY],
    // A scheduled mirror of the upstream Playwright image; no suite runs it.
    ['.github/workflows/ci-playwright-container.yml', DEPLOY],
    // The dev-environment checks: the flox boot check and the sandbox
    // selftests, which are the only suites reading the dev-stack scripts.
    ['.github/workflows/ci-dev-setup.yml', DEV_ENV],
    ['.github/workflows/dev-sandbox-selftest.yml', DEV_ENV],
    // The docs suites gate documentation PRs, which claim the prose lane.
    // ci-docs-check is reusable but its one caller is the survey check, whose
    // radius spans the frontend sources it compares against the docs.
    ['.github/workflows/docs-preview-trigger.yml', PROSE_SUITE],
    ['.github/workflows/ci-survey-sdk-check.yml', [JAVASCRIPT, PROSE_SUITE]],
    ['.github/workflows/ci-docs-check.yml', [JAVASCRIPT, PROSE_SUITE]],
    // Scripts and config on the automation lane above.
    ['.github/scripts/assign-reviewers.js', REPO_AUTOMATION],
    ['.github/scripts/assign-reviewers.test.js', REPO_AUTOMATION],
    ['.github/scripts/codeowners.js', REPO_AUTOMATION],
    ['.github/scripts/label-pr-from-title.js', REPO_AUTOMATION],
    ['.github/scripts/label-pr-from-title.test.js', REPO_AUTOMATION],
    ['.github/scripts/minimize-superseded-comments.mjs', REPO_AUTOMATION],
    ['.github/scripts/autoresolve/**', REPO_AUTOMATION],
    ['.github/scripts/monitor-github-rate-limit.js', REPO_AUTOMATION],
    ['.github/scripts/monitor-github-rate-limit.test.js', REPO_AUTOMATION],
    ['.github/scripts/weekly-*.mjs', REPO_AUTOMATION],
    ['.github/scripts/eng-analytics-weekly-digest.mjs', REPO_AUTOMATION],
    ['.github/scripts/ci-alerts-devex.js', REPO_AUTOMATION],
    ['.github/scripts/ci-alerts-devex.test.js', REPO_AUTOMATION],
    ['.github/scripts/ci_flake_overseer.py', REPO_AUTOMATION],
    ['.github/scripts/test_ci_flake_overseer.py', REPO_AUTOMATION],
    ['.github/scripts/compare-ci-runners.py', REPO_AUTOMATION],
    ['.github/scripts/report_workflow_run_traces.py', REPO_AUTOMATION],
    ['.github/scripts/test_report_workflow_run_traces.py', REPO_AUTOMATION],
    ['.github/auto-assign-labels.json', REPO_AUTOMATION],
    ['.github/dependabot.yml', REPO_AUTOMATION],
    ['.github/renovate.json5', REPO_AUTOMATION],
    // Scripts run only by ci-backend, ci-python, or ci-dagster.
    ['.github/scripts/check-dagster-paths.py', PYTHON],
    ['.github/scripts/test_check_dagster_paths.py', PYTHON],
    ['.github/scripts/check-dwh-source-agnostic.py', PYTHON],
    ['.github/scripts/check-operator-parity.py', PYTHON],
    ['.github/scripts/check-version-specifiers.py', PYTHON],
    ['.github/scripts/coverage_report.py', PYTHON],
    ['.github/scripts/coverage_report.py.lock', PYTHON],
    ['.github/scripts/test_coverage_report.py', PYTHON],
    ['.github/scripts/list-removed-renamed-paths.sh', PYTHON],
    ['.github/scripts/migration-deletion-allowlist.txt', PYTHON],
    ['.github/scripts/signal-fanout', PYTHON],
    ['.github/scripts/verify-new-snapshots.sh', PYTHON],
    ['.github/scripts/post-ch-migration-section.mjs', PYTHON],
    ['.github/scripts/post-django-migration-section.mjs', PYTHON],
    ['.github/scripts/post-coverage-section.mjs', PYTHON],
    ['.github/scripts/post-eval-section.mjs', PYTHON],
    // CI-report sections and helpers owned by one suite each.
    ['.github/scripts/post-playwright-section.mjs', FULLSTACK],
    ['.github/scripts/verify-playwright-new-tests-and-snapshots.sh', FULLSTACK],
    ['.github/scripts/post-snapshot-section.mjs', FULLSTACK],
    ['.github/scripts/count-snapshot-changes.sh', FULLSTACK],
    ['.github/scripts/fixtures/**', FULLSTACK],
    ['.github/scripts/verify-storybook-new-stories.sh', JAVASCRIPT],
    ['.github/scripts/post-hobby-section.mjs', HOBBY],
    ['.github/scripts/desktop/**', DESKTOP],
    ['.github/scripts/patch-cli-npm-installer.mjs', DEPLOY],
    ['.github/scripts/patch-cli-npm-installer.test.mjs', DEPLOY],
    ['.github/scripts/check-docs-links.js', PROSE_SUITE],
    ['.github/scripts/trigger-vercel-preview.sh', PROSE_SUITE],
    ['.github/scripts/post-docs-preview-section.mjs', PROSE_SUITE],
    // Validates the AGENTS.md symlinks that the agents lane's build reads.
    ['.github/scripts/check-agents-md-symlinks.sh', 'agents-lane'],
    // Run only by the husky pre-commit hook, whose config already sits on the
    // repo-config lane. No CI suite executes them.
    ['.github/scripts/check-access-control-doc-sync.sh', 'repo-config-lane'],
    ['.github/scripts/check-fixture-provenance.sh', 'repo-config-lane'],
    ['.github/scripts/check-product-scaffold.sh', 'repo-config-lane'],
    // Composite actions held to the workflows that use them. The setup and
    // helper actions used across language families (pnpm-install, paths-filter,
    // setup-sqlx-cli, setup-protoc, setup-sccache, docker-meta, semgrep-ci) and
    // the lane-feeding rust-compute-affected stay on the blanket below.
    ['.github/actions/build-n-cache-image/**', FULLSTACK],
    ['.github/actions/commit-snapshots/**', FULLSTACK],
    ['.github/actions/trunk-quarantine-gate/**', FULLSTACK],
    ['.github/actions/setup-emsdk/**', FULLSTACK],
    ['.github/actions/desktop-build-agent-release/**', DESKTOP],
    ['.github/actions/desktop-restore-turbo-cache/**', DESKTOP],
    ['.github/actions/setup-python-cached/**', PYTHON],
    // Also used by ci-scripts.yml, which is universal, so the node lane is the
    // only radius left to claim.
    ['.github/actions/report-jest-timings/**', NODE],
    ['.github/actions/get-pr-labels/**', APP_IMAGE],
    ['.github/actions/wait-for-check/**', HOBBY],
    // Problem matchers and coverage config registered only by the Python
    // suites, and the ClickHouse version matrix the backend, dagster, and E2E
    // suites test against.
    ['.github/mypy-problem-matcher.json', PYTHON],
    ['.github/ty-problem-matcher.json', PYTHON],
    ['.github/openapi-problem-matcher.json', PYTHON],
    ['.github/coverage-core.cfg', PYTHON],
    ['.github/clickhouse-versions.json', FULLSTACK],
    ['.github/dockerignore-drop-allowlist.txt', FULLSTACK],
    // Issue templates render on github.com and compile into nothing.
    ['.github/ISSUE_TEMPLATE/**', 'repo-config-lane'],
    // Deployment templates with no in-repo reader; nothing tests them.
    ['.github/pr-deploy/**', DEPLOY],
    // Ownership data on the shared ownership lane (see OWNERSHIP): the
    // CODEOWNERS the review bots read, and .github/'s own tree ownership.
    ['.github/CODEOWNERS', OWNERSHIP],
    ['.github/owners.yaml', OWNERSHIP],
    // The vendored paths-filter action and its CI (see CI_TOOLING). The
    // .depot/ shadow of the action follows through canonicalPath.
    ['.github/actions/paths-filter/**', CI_TOOLING],
    ['.github/workflows/ci-paths-filter.yml', CI_TOOLING],
    // Feed turbo-discover's backend product selection, so they take the
    // python lanes the same way the snob selector does.
    ['.github/scripts/schema-impact.js', PYTHON],
    ['.github/scripts/schema-impact.test.js', PYTHON],
    ['.github/scripts/schema_usage_scan.py', PYTHON],
    ['.github/scripts/test_schema_usage_scan.py', PYTHON],
    // Reusable image builder called by the rust smoke build and the rust
    // image CD (ci-frontend only names it in a comment), so it spans exactly
    // those two radii.
    ['.github/workflows/_rust-build-images.yml', [RUST, DEPLOY]],

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
    // Prettier still formats the nodejs tree (ci-nodejs runs its check), so
    // its ignore file is a JS toolchain setting like the two above.
    ['.prettierignore', JAVASCRIPT],
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
    // Single-purpose images ahead of the fallback: each is read by exactly one
    // workflow or suite, whose rule above already carries the radius.
    // Dockerfile.llm-analytics is built only by its master-push CD workflow,
    // Dockerfile.ml-mirror-image-scrub only from nodejs/ sources, and the
    // playwright and sandbox images host suites that run both language
    // families. Everything else at the root, the unified app image included,
    // backs E2E, hobby, and production, which is the app-image radius; no
    // rust suite builds from a root Dockerfile. The build-context ignore file
    // belongs with them.
    ['Dockerfile.llm-analytics', DEPLOY],
    ['Dockerfile.ml-mirror-image-scrub', NODE],
    ['Dockerfile.playwright', FULLSTACK],
    ['Dockerfile.sandbox', FULLSTACK],
    ['Dockerfile*', APP_IMAGE],
    ['.dockerignore', APP_IMAGE],
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
    // The per-suite test-selection scripts at the root of tools/, ahead of the
    // catch-all that widens anything else there. Each decides which of one
    // suite's tests run on a PR, so an under-selection can only mask conflicts
    // that suite's lanes already serialize: the snob shadow, its verdict, and
    // the testmon fanout list select Django tests, the dagster selector its
    // own suite, and the playwright pair the E2E specs.
    ['tools/snob_backend_test_selection_shadow.py', PYTHON],
    ['tools/test_snob_backend_test_selection_shadow.py', PYTHON],
    ['tools/test_selection_verdict.py', PYTHON],
    ['tools/test_test_selection_verdict.py', PYTHON],
    ['tools/dagster_test_selection.py', PYTHON],
    ['tools/test_dagster_test_selection.py', PYTHON],
    ['tools/testmon_high_fanout_files.txt', PYTHON],
    ['tools/playwright_spec_selection.py', FULLSTACK],
    ['tools/test_playwright_spec_selection.py', FULLSTACK],
    ['tools/playwright_area_map.json', FULLSTACK],
    // The ownership data and its validation tooling share one lane. The root
    // owners.yaml is the fallback every path resolves through when no nearer
    // file claims it. A product's own owners.yaml is not here: it keeps its
    // product lane.
    ['tools/owners/**', OWNERSHIP],
    ['owners.yaml', OWNERSHIP],
    // The quarantine list covers the pytest, jest, and playwright suites at
    // once, and turbo-discover reads it to drop products from the backend
    // matrix. Every reader sits inside the two language families; no rust
    // suite consumes it. A schema change and an entry in the old format meet
    // in the same file, which git serializes as a textual conflict.
    ['.test_quarantine.json', FULLSTACK],
    // The hobby install scripts, ahead of the bin/ blanket. Only the hobby
    // smoke test and the installer CI read them, and both workflows sit on the
    // same lane above, so a hobby change and the workflow change that runs it
    // stay serialized against each other and nothing else.
    ['bin/hobby-installer/**', HOBBY],
    ['bin/hobby-ci.py', HOBBY],
    ['bin/hobby-ci-setup-user.py', HOBBY],
    ['bin/deploy-hobby', HOBBY],
    ['bin/upgrade-hobby', HOBBY],
    ['bin/migrate-storage-hobby', HOBBY],
    ['bin/migrate-session-recordings-hobby', HOBBY],
    // Called by the hobby storage-migration scripts above, so it has to share
    // their lane.
    ['bin/migrate-minio-to-seaweedfs', HOBBY],
    // Entrypoints and configuration the unified app image bakes in, plus the
    // scripts docker-compose.base.yml runs as service commands. The image
    // backs E2E, hobby, and production, which is the app-image radius. The
    // exact-name rows precede the wildcard rows that would otherwise claim
    // them for the dev stack.
    ['bin/docker-server*', APP_IMAGE],
    ['bin/docker-worker*', APP_IMAGE],
    ['bin/docker-migrate', APP_IMAGE],
    ['bin/migrate', APP_IMAGE],
    ['bin/migrate-check', APP_IMAGE],
    ['bin/celery-queues.env', APP_IMAGE],
    ['bin/posthog-node', APP_IMAGE],
    ['bin/temporal-django-worker', APP_IMAGE],
    ['bin/granian_metrics.py', APP_IMAGE],
    ['bin/unit_metrics.py', APP_IMAGE],
    ['bin/start-backend', APP_IMAGE],
    ['bin/start-frontend', APP_IMAGE],
    // The schema and taxonomy codegen pipeline, which turns
    // frontend/src/queries/schema.json into posthog/schema.py and the other
    // generated artifacts both families read.
    ['bin/build-*', PRODUCT_SURFACE],
    ['bin/patch-schema-*', PRODUCT_SURFACE],
    ['bin/split-schema-enums.py', PRODUCT_SURFACE],
    // Scripts run only by the Python suites.
    ['bin/check_uv_python_compatibility.py', PYTHON],
    ['bin/find_python_dependencies.py', PYTHON],
    ['bin/test/**', PYTHON],
    ['bin/ruff.sh', PYTHON],
    // Scripts run only by the frontend and storybook suites, plus the pnpm
    // lifecycle hook package.json declares.
    ['bin/find-affected-stories', JAVASCRIPT],
    ['bin/find-affected-stories.test.mjs', JAVASCRIPT],
    ['bin/frontend-exclude-filter', JAVASCRIPT],
    ['bin/validate-setup-tasks.mjs', JAVASCRIPT],
    ['bin/lint-feature-flag-sorting.mjs', JAVASCRIPT],
    ['bin/fix-rdkafka-paths', JAVASCRIPT],
    ['bin/create-notebook-node.sh', JAVASCRIPT],
    // The Hog CLI backs the Hog suite, the jest-timing helpers feed
    // report_test_timings, the dockerignore check runs in container-images-ci,
    // and the sandbox scripts are baked into the sandbox image; all of those
    // sit on the fullstack lanes already.
    ['bin/hog', FULLSTACK],
    ['bin/hoge', FULLSTACK],
    ['bin/report-jest-timings', FULLSTACK],
    ['bin/render-jest-timings-example', FULLSTACK],
    ['bin/dockerignore-drop-check', FULLSTACK],
    ['bin/sandbox*', FULLSTACK],
    ['bin/sandbox-shims/**', FULLSTACK],
    ['bin/generate_personhog_proto.sh', PROTO],
    // Runs in the bot-IP update workflow on the automation lane.
    ['bin/update-bots-list', REPO_AUTOMATION],
    // The local development stack: process lists, launchers, readiness checks,
    // storage upgrades, and developer helpers. Nothing in CI reads them except
    // the dev-setup check and the sandbox selftests, which share the lane.
    ['bin/mprocs*.yaml', DEV_ENV],
    ['bin/e2e-test-runner', DEV_ENV],
    ['bin/start', DEV_ENV],
    ['bin/start-*', DEV_ENV],
    ['bin/dev-*', DEV_ENV],
    ['bin/check_*', DEV_ENV],
    ['bin/clickhouse-*', DEV_ENV],
    ['bin/docker-*', DEV_ENV],
    ['bin/temporal-*', DEV_ENV],
    ['bin/verify-*', DEV_ENV],
    ['bin/upgrade-*', DEV_ENV],
    ['bin/helpers/**', DEV_ENV],
    ['bin/wait-for-postgres-tables', DEV_ENV],
    ['bin/ensure-local-setup', DEV_ENV],
    ['bin/dump_hogvmrs_stl', DEV_ENV],
    ['bin/download-sentiment-model', DEV_ENV],
    ['bin/inject_mcp_intents.py', DEV_ENV],
    ['bin/install-hogli-completion', DEV_ENV],
    ['bin/phw', DEV_ENV],
    ['bin/posthog-worktree', DEV_ENV],
    ['bin/rust-jumphost', DEV_ENV],
    ['bin/send-dev-metrics.sh', DEV_ENV],
    ['bin/setup-gateway-e2e', DEV_ENV],
    ['bin/sync-storage', DEV_ENV],
    ['bin/warm-flags-cache', DEV_ENV],
    // bin/ appears in the backend, frontend, and E2E path filters alike, and
    // what remains here is read across families: hogli and turbo drive the
    // suites, bin/docker is the image entrypoint, and download-mmdb and the
    // wait-for-docker pair run in backend, frontend, nodejs, and rust CI.
    ['bin/**', UNIVERSAL],
    // pnpm patches resolve inside the JS workspace the same way pnpm-lock.yaml
    // does, and the python suites never execute the patched packages.
    ['patches/**', JAVASCRIPT],
    // Names the Depot project every container build and runner is billed and
    // cached against, which is infrastructure routing rather than anything a
    // suite reads: a wrong project fails its own PR's builds alone, never
    // jointly with another PR. rust/depot.json is deliberately not here: it
    // configures builds of that workspace only, and the rust rules below hold
    // it to them.
    ['depot.json', 'repo-config-lane'],
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
    // Configures the local Trunk CLI only (merge / status / cancel); linting
    // is deliberately disabled there. The queue's own behavior lives
    // server-side and in the lane rules, which stay universal.
    '.trunk',
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

// .depot/ holds Depot-runner shadows of the workflows and composite actions in
// .github/, kept apples-to-apples with their canonicals by the shadow-drift
// check, and their statuses are non-blocking. A shadow can only affect what
// its canonical affects, so it resolves through the canonical's rules: the
// ci-backend shadow takes the python lanes, and a shadow of something unplaced
// still lands on the .github/** blanket.
const DEPOT_MIRROR_PREFIX = '.depot/'

function canonicalPath(file) {
    return file.startsWith(DEPOT_MIRROR_PREFIX) ? `.github/${file.slice(DEPOT_MIRROR_PREFIX.length)}` : file
}

// The domain of the first rule matching the file, or null when no rule claims
// it and when a rule claims it as an explicit non-tripwire. Both mean the same
// thing to every caller: the file falls through to the ordinary rules.
function tripwireDomain(file) {
    const resolved = canonicalPath(file)
    const matched = TRIPWIRE_MATCHERS.find(([re]) => re.test(resolved))
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
//   2. The product is absent from the tach map, the real Python import graph,
//      so no Python file under a source root imports it.
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

// A product the tach map walked has a known importer set. One absent from the
// map (no Python with an import edge under a source root, or excluded by
// tach.toml), or a map that could not be read at all, has none.
function isTachDeclared(product, tachGraph) {
    if (!tachGraph) {
        return false
    }
    return tachGraph.graph.has(product)
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

// --- Rust crate inventory ---

// Discovers workspace crates as (directory, crate name) pairs. Crate names can
// differ from directory names, and file paths only carry the directory, so both
// are needed to translate a changed path into a crate.
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
                const name = parseCrateName(fs.readFileSync(full, 'utf8'))
                if (name) {
                    // A package.json beside the Cargo.toml means the crate also
                    // builds an npm package, so its lane extends past rust/.
                    const publishesNpmPackage = fs.existsSync(path.join(dir, 'package.json'))
                    crates.push({ dir: relative, name, publishesNpmPackage })
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

// The dependency edges between crates deliberately live elsewhere:
// rust/affected-services, the determinator ci-rust.yml selects tests with,
// is the sole authority on which crates a change set affects, and its answer
// reaches this script through RUST_AFFECTED_CRATES. The inventory only names
// the crates: it maps a changed path to the crate holding it, enumerates the
// full set a widening claims, and flags the crates that also publish npm
// packages.
//
// Returns null when the inventory can't be built. Callers must treat null as
// "unknown crates" and widen to every target, never as "no crates". Widening
// past the rust lanes is deliberate: without the inventory the script cannot
// tell which crate a rust path belongs to either, so the rust targets alone
// would not be a superset of what the change can break.
function loadRustInventory(repoRoot) {
    try {
        const crates = discoverRustCrates(repoRoot)
        if (crates.length === 0) {
            return null
        }
        const crateNames = new Set(crates.map((crate) => crate.name))
        const nativeBindings = new Set(crates.filter((crate) => crate.publishesNpmPackage).map((crate) => crate.name))
        // Longest directory first so rust/common/hogvm resolves to its own crate
        // rather than to rust/common.
        const byDir = crates
            .map((crate) => ({ dir: crate.dir, name: crate.name }))
            .sort((a, b) => b.dir.length - a.dir.length)
        return { crateNames, byDir, nativeBindings }
    } catch (error) {
        console.error(`Rust crate inventory unavailable (${error.message}); widening to every target`)
        return null
    }
}

// --- Target computation ---

const pyProduct = (product) => `py:product:${product}`
const feProduct = (product) => `fe:product:${product}`
const rustCrate = (crate) => `rust:crate:${crate}`

// Internal sentinel for a file whose crate radius only the determinator's
// answer can state, because the path names no crate directory to seed from
// (rust/Cargo.lock). Consumed by the determinator resolution at the end of
// computeTargets and never uploaded.
const RUST_DETERMINATOR = 'rust:determinator'

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
    const { products, services, rustInventory } = context
    if (!rustInventory || !services) {
        return null
    }
    const targets = new Set([
        'py:core',
        'fe:core',
        'node:ingestion',
        'agents',
        'deploy',
        'hobby',
        'repo-automation',
        'dev-env',
        'ownership',
        'ci-tooling',
    ])
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
    for (const crate of rustInventory.crateNames) {
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
    if (!context.rustInventory) {
        return false
    }
    for (const crate of context.rustInventory.crateNames) {
        targets.add(rustCrate(crate))
    }
    return true
}

// rust/Cargo.lock sits in no crate directory, so its radius is whatever the
// determinator's answer says the resolution change moved. The sentinel defers
// to that answer, which the resolution at the end of computeTargets reads,
// falling back to every crate when it is missing, empty, or in disagreement.
function addCargoLockLanes(targets, context) {
    if (!context.rustInventory) {
        return false
    }
    targets.add(RUST_DETERMINATOR)
    return true
}

function addNodeLanes(targets) {
    targets.add('node:ingestion')
    return true
}

function addFullstackLanes(targets, context) {
    return addPythonLanes(targets, context) && addJavaScriptLanes(targets, context)
}

// Release and CD workflows publish artifacts from master pushes, tags, or
// opt-in labels. No required pull-request or merge-queue check runs them, so a
// conflict between one of them and any other PR is not a combination the queue
// can test, and serializing the two buys no coverage. One shared lane, on the
// same reasoning as repo-config.
function addDeployLane(targets) {
    targets.add('deploy')
    return true
}

function addHobbyLane(targets) {
    targets.add('hobby')
    return true
}

function addHogboxPreviewLane(targets) {
    targets.add('tools:hogbox-preview')
    return true
}

function addCliArtifactLanes(targets) {
    targets.add('cli')
    targets.add('svc:mcp')
    return true
}

// The desktop-* workflows build and test only products/desktop, so their
// radius is that product's two lanes. The guard widens when the product is
// gone, because the lanes would then name targets no other PR can claim.
function addDesktopLanes(targets, context) {
    if (!context.products.includes('desktop')) {
        return false
    }
    targets.add(pyProduct('desktop'))
    targets.add(feProduct('desktop'))
    return true
}

// A workflow that defines one service's suite can be held to that service's
// lane. The guard widens when the directory no longer exists, so a renamed
// service does not leave its workflow claiming a lane no other PR can reach.
function addServiceSuiteLane(service) {
    return (targets, context) => {
        if (!context.services || !context.services.includes(service)) {
            return false
        }
        targets.add(`svc:${service}`)
        return true
    }
}

// A domain whose lanes are a fixed list of always-known targets. Only for
// targets allKnownTargets carries unconditionally (the static base set,
// STANDALONE_TREES values, and TOOLS_INDEPENDENT); a dynamic target needs a
// guarded function like the service one above.
function laneOf(...targetNames) {
    return (targets) => {
        for (const name of targetNames) {
            targets.add(name)
        }
        return true
    }
}

function addAppImageLanes(targets, context) {
    targets.add('hobby')
    targets.add('deploy')
    return addFullstackLanes(targets, context)
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
// scoped to a single proto subdirectory, and so is a file outside proto/
// entirely (the Proto CI workflow reaches this domain that way). A subdirectory
// the table does not name has unknown consumers and widens, which is what makes
// adding a tree without declaring it here safe rather than silent.
function addProtoLanes(targets, context, file) {
    const segments = file.split('/')
    const trees =
        segments[0] !== 'proto' || segments.length === 2
            ? [...PROTO_TREES.keys()]
            : [segments[1]].filter((tree) => PROTO_TREES.has(tree))
    if (trees.length === 0 || !context.rustInventory) {
        return false
    }
    for (const tree of trees) {
        const { crates, domains } = PROTO_TREES.get(tree)
        // A crate renamed out from under the table would drop the rust half
        // silently, which is the under-reporting direction.
        if (crates.some((crate) => !context.rustInventory.crateNames.has(crate))) {
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
    [FULLSTACK, addFullstackLanes],
    [DEPLOY, addDeployLane],
    [HOBBY, addHobbyLane],
    [HOGBOX_PREVIEW, addHogboxPreviewLane],
    [CLI_ARTIFACTS, addCliArtifactLanes],
    [DESKTOP, addDesktopLanes],
    [REPO_AUTOMATION, laneOf('repo-automation')],
    [DEV_ENV, laneOf('dev-env')],
    [OWNERSHIP, laneOf('ownership')],
    [CI_TOOLING, laneOf('ci-tooling')],
    [APP_IMAGE, addAppImageLanes],
    [PROSE_SUITE, laneOf('prose')],
    ['livestream-suite', laneOf('livestream')],
    ['phrocs-suite', laneOf('tools:phrocs')],
    ['terraform-suite', laneOf('terraform')],
    ['repo-config-lane', laneOf('repo-config')],
    ['agents-lane', laneOf('agents')],
])
for (const service of ['llm-gateway', 'oauth-proxy', 'agent-proxy', 'integration-service']) {
    DOMAIN_LANES.set(`service:${service}`, addServiceSuiteLane(service))
}

// Returns false when the file's domain is universal, which is the caller's cue
// to abandon the per-file accumulation and report the whole set. A rule may
// carry a list of domains for a file read on both sides of a split; the file
// claims every listed domain's lanes, and one that cannot enumerate widens the
// whole set as it would alone.
function applyTripwireDomain(domain, file, targets, context) {
    if (Array.isArray(domain)) {
        return domain.every((entry) => applyTripwireDomain(entry, file, targets, context))
    }
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
        rustInventory,
        tachGraph,
        contractSurfaces = new Map(),
        productWorkspaces = new Map(),
        backendDetachedProducts = new Set(),
        tachDeclaredProducts = listTachDeclaredProducts(products, tachGraph),
        deletedFiles = new Set(),
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
        // zips products/*/skills/* (which ci-agent-skills.yml gates), the
        // skills build syncs .agents/skills/, and ci-python.yml runs the
        // pr-approval-agent suite over .stamphog/. All of them fall through to
        // their directory rules below.
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
            if (!rustInventory) {
                targets.add('rust:unresolved')
                continue
            }
            const crate = rustInventory.byDir.find(
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
                if (isBackend && deletedFiles.has(file)) {
                    // The tach map is read from the head tree, so a deleted or
                    // renamed-away file is not in it and its importers are
                    // unknown. The PR that removes a facade module beside a
                    // caller it missed is the exact conflict lanes exist for.
                    allPyProducts()
                } else if (isolatedProducts.has(product)) {
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
                    // The bound only holds for a product the tach map walked.
                    // One absent from the map has no known importer set, so
                    // it still widens below.
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

    // The rust:crate: targets accumulated above are seeds: the crates the
    // changed paths sit in, plus the ones the proto and workspace rules named.
    // The dependency closure over them is the determinator's answer, the same
    // rust/affected-services run ci-rust.yml selects tests with, delivered
    // through RUST_AFFECTED_CRATES. This script holds no crate dependency
    // edges of its own, so a missing answer widens to every crate, and so does
    // an answer that omits a seed, which means the determinator and this
    // script disagree about the workspace. An answer naming no crate widens
    // too: it is a real verdict on a lockfile edit that moved no resolution,
    // but claiming nothing for it would reach the empty-set guard below and
    // widen past the rust lanes entirely.
    const needsDeterminator = targets.delete(RUST_DETERMINATOR)
    const rustSeeds = [...targets]
        .filter((target) => target.startsWith('rust:crate:'))
        .map((target) => target.slice('rust:crate:'.length))
    if (needsDeterminator || rustSeeds.length > 0) {
        if (!rustInventory) {
            return everything(context)
        }
        const answer = context.rustAffectedCrates
        const affectedCrates =
            answer && answer.length > 0 && rustSeeds.every((seed) => answer.includes(seed))
                ? answer
                : [...rustInventory.crateNames]
        for (const crate of affectedCrates) {
            targets.add(rustCrate(crate))
        }
        // A crate that also builds an npm package compiles into a native module
        // the JS workspace imports, so the radius does not end at rust/. The
        // dependents are found through package.json rather than Cargo.toml,
        // which is why the determinator's answer alone stops one edge short.
        const bindings = rustInventory.nativeBindings || new Set()
        if (affectedCrates.some((crate) => bindings.has(crate))) {
            for (const target of NATIVE_BINDING_CONSUMER_LANES) {
                targets.add(target)
            }
        }
    }

    if (targets.has('rust:unresolved')) {
        targets.delete('rust:unresolved')
        if (rustInventory) {
            for (const crate of rustInventory.crateNames) {
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

// The tach map is the real Python import graph (`tach map` reads the imports
// that `tach check` enforces in CI, so it cannot drift from what is
// importable). Turbo-style dashed names cross the boundary in both directions;
// product directories are underscored.
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
    const { loadTachModuleGraph, tachDependents } = require('./turbo-discover')
    const graph = loadTachModuleGraph(repoRoot)
    return graph === null ? null : { graph, tachDependents }
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

// The crate list rust-compute-affected produced for this diff, as a JSON
// array. It is the determinator's affected set (the changed crates plus the
// closure of their dependents, with the runtime spawn edges its rules
// declare), so it arrives as a finished answer rather than as seeds to close
// over. The workflow only runs the determinator when the change set touches
// rust/ or proto/, so on every other PR this is unset and never read.
const RUST_AFFECTED_CRATES_ENV = 'RUST_AFFECTED_CRATES'

// Returns null for unknown, which the caller widens on. The determinator
// answers for the whole diff rather than for the rust paths alone, so this is
// a superset of their own contribution, which is the safe direction.
//
// A name the crate inventory does not know means the two disagree about the
// workspace, and a disagreement resolves to unknown rather than to a lane list
// built from half of it.
function parseRustAffectedCrates(raw, rustInventory) {
    if (!rustInventory || !raw) {
        return null
    }
    let crates
    try {
        crates = JSON.parse(raw)
    } catch (error) {
        console.error(`${RUST_AFFECTED_CRATES_ENV} is not JSON (${error.message}); a rust change claims every crate`)
        return null
    }
    if (!Array.isArray(crates) || crates.some((crate) => typeof crate !== 'string')) {
        console.error(`${RUST_AFFECTED_CRATES_ENV} is not a list of crate names; a rust change claims every crate`)
        return null
    }
    const unknown = crates.filter((crate) => !rustInventory.crateNames.has(crate))
    if (unknown.length > 0) {
        console.error(
            `The determinator named crates the inventory does not hold (${unknown.join(', ')}); ` +
                'a rust change claims every crate'
        )
        return null
    }
    return crates
}

function buildContext(repoRoot) {
    const products = listProducts(repoRoot)
    const tachGraph = loadTachGraph(repoRoot)
    const rustInventory = loadRustInventory(repoRoot)
    const contractSurfaces = loadContractSurfaces(repoRoot, products)
    return {
        products,
        rustAffectedCrates: parseRustAffectedCrates(process.env[RUST_AFFECTED_CRATES_ENV], rustInventory),
        services: listServices(repoRoot),
        isolatedProducts: listIsolatedProducts(repoRoot, products, contractSurfaces),
        contractSurfaces,
        productWorkspaces: loadProductWorkspaces(repoRoot, products),
        backendDetachedProducts: loadBackendDetachedProducts(repoRoot, products, tachGraph),
        tachDeclaredProducts: listTachDeclaredProducts(products, tachGraph),
        semgrepDomains: loadSemgrepDomains(repoRoot),
        rustInventory,
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
    parseCrateName,
    parsePytestIgnores,
    parseSemgrepLanguages,
    parseWorkspacePackageGlobs,
    semgrepDomain,
    stripJsonComments,
    tripwireDomain,
    parseRustAffectedCrates,
    ALL,
    CARGO_LOCK,
    CLI_ARTIFACTS,
    DEPLOY,
    DESKTOP,
    FULLSTACK,
    HOBBY,
    HOGBOX_PREVIEW,
    JAVASCRIPT,
    NATIVE_BINDING_CONSUMER_LANES,
    NODE,
    PROTO_TREES,
    PYTHON,
    REPO_ROOT,
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
            // The change list carries deleted paths too; the tree no longer does.
            const deletedFiles = new Set(changedFiles.filter((file) => !fs.existsSync(path.join(REPO_ROOT, file))))
            result = computeTargets(changedFiles, { ...buildContext(REPO_ROOT), deletedFiles })
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
