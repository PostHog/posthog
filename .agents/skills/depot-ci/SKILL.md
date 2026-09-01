---
name: depot-ci
description: >
  Configures and manages Depot CI, a drop-in replacement for GitHub Actions that runs workflows
  entirely within Depot. Use when migrating GitHub Actions workflows to Depot CI, running
  `depot ci migrate`, managing Depot CI secrets and variables, running workflows with
  `depot ci run`, debugging Depot CI runs with `depot ci run list`, `depot ci status`,
  `depot ci logs`, `depot ci diagnose`, or `depot ci ssh`, inspecting test results with
  `depot tests` or run artifacts with `depot ci artifacts`, checking workflow compatibility,
  or understanding Depot CI capabilities. Also use when the user mentions .depot/ directory,
  depot ci commands, or asks about running GitHub Actions workflows on Depot's infrastructure
  without GitHub-hosted runners. Also use when comparing what Depot CI and GitHub Actions
  report for a skipped, empty-matrix or continue-on-error job, or when working out whether a
  check run satisfies a required status check or a merge queue.
---

# Depot CI

Depot CI is a programmable CI system for engineers and agents. Workflows in Depot CI run entirely on Depot compute with built-in job visibility, debuggability, and control. GitHub Actions is the first syntax Depot CI supports: migrate your existing GitHub Actions workflows, and get fast, reliable runs on optimized infrastructure.

This SKILL.md covers the core workflow plus the most common commands. Detailed flag tables, JSON output shapes, and less-common commands live in three reference files under `references/`, pointed to from the relevant sections below. Load a reference file only when you need detail it points to.

<!-- PostHog-local section. Keep it when resyncing from upstream; see UPSTREAM.md. -->

PostHog addition: read [references/posthog-check-run-semantics.md](references/posthog-check-run-semantics.md) before you reason about what a Depot CI run reports to GitHub.
It carries measured results for what Depot CI and GitHub Actions each post for a skipped, empty-matrix or `continue-on-error` job, how GitHub and the Trunk merge queue score those conclusions against a required status check, and the check-run naming and rerun differences between the two engines.
This repo runs Depot CI workflows out of `.depot/workflows/` alongside GitHub Actions, so both engines report on the same commit.

<!-- End PostHog-local section. -->

## Architecture

Three subsystems: **compute** (provisions and executes work), **orchestrator** (schedules multi-step workflows, handles dependencies), **GitHub Actions parser** (translates Actions YAML into orchestrator workflows). The system is fully programmable.

## Common flags

Nearly every `depot ci` command (and `depot tests`) accepts:

- `--org <id>`: organization ID, required when the user belongs to multiple organizations (see Org Context Check below).
- `--token <token>`: Depot API token.
- `-o, --output json`: machine-readable output, useful for agents and scripting. Most `depot ci` subcommands accept the `-o` shorthand, but `depot tests`, `depot ci secrets`, and `depot ci vars` accept only the long `--output` form.

Per-command tables in the reference files omit these to cut noise; assume they're available.

## Org Context Check for Multi-Org Users

If a user belongs to multiple organizations, before setup/migration or if CI commands can't find expected workflows, verify Depot org context first:

```bash
depot org show              # Current org ID
depot org list              # Orgs the user belongs to
depot org switch <org-id>   # Option A: switch default org for this shell/session

# Option B: keep current org and target explicitly per command
depot ci run --org <org-id> --workflow .depot/workflows/ci.yml
```

Use `--org <org-id>` when the workflow/repo lives in a different org than the current default.

## Getting Started

### 1. Install the Depot Code Access GitHub App

Depot dashboard → Settings → GitHub Code Access → Connect to GitHub. (If you've used Claude Code on Depot, this may already be installed.)

### 2. Migrate workflows

```bash
depot ci migrate
```

This interactive wizard:

1. Checks that the Depot Code Access app is installed and configured.
1. Discovers all workflows in `.github/workflows/` and analyzes each for Depot CI compatibility.
1. Copies selected workflows to `.depot/workflows/` with inline corrections and comments, and copies local actions from `.github/actions/` to `.depot/actions/`.
1. Detects secrets and variables referenced in workflows and prints next steps for importing them.

Your `.github/` directory is untouched, so workflows run in both GitHub and Depot simultaneously. **Warning:** workflows that cause side effects (deploys, artifact updates) will execute twice.

### 3. Import secrets and variables

```bash
depot ci migrate secrets-and-vars
```

This creates and runs a one-shot GitHub Actions workflow on a temporary branch that reads your existing secrets and variables and imports them into Depot CI. You can also add them manually with `depot ci secrets add` / `depot ci vars add` (see Managing Secrets and Variables below).

**For migration detail** (the `preflight`/`workflows`/`secrets-and-vars` subcommands, their flag tables, exactly what gets transformed, and manual setup), read `references/migration.md`.

## Managing Secrets and Variables

Secrets (referenced as `${{ secrets.NAME }}`, encrypted, never readable after creation) and variables (referenced as `${{ vars.NAME }}`, values readable) share a **variant model**. A name groups one or more variants; each variant holds a value plus optional selectors (`--repo`, `--env`, `--branch`, `--workflow`) that match jobs by repository, GitHub environment, branch, and workflow file. A variant with no selectors applies to every job in the organization. The CLI manages all four selector kinds directly, so variants no longer require the dashboard.

Secret values come from an interactive prompt, piped stdin, or `KEY=VALUE` bulk pairs (no `--value` flag for secrets). Variable values use `--value`, a prompt, or `KEY=VALUE` pairs.

```bash
# Secrets: add (prompt or piped stdin), list, remove
depot ci secrets add SECRET_NAME                                   # Prompts securely
printf '%s' "$NPM_TOKEN" | depot ci secrets add SECRET_NAME        # From stdin (scripts)
depot ci secrets add SECRET_NAME --repo owner/repo --branch main   # Scoped variant
depot ci secrets list
depot ci secrets remove SECRET_NAME

# Variables: add, list, remove
depot ci vars add VAR_NAME --value "some-value"
depot ci vars add VAR_NAME --value "prod" --repo owner/repo --env production   # Scoped variant
depot ci vars list
depot ci vars remove VAR_NAME
```

**For the full command surface** (the `set`, `bulk`, and `get` secrets subcommands, every flag table, and how Depot resolves which variant wins at run time), read `references/secrets-and-variables.md`.

### Credential safety

Treat credentials as sensitive input and never echo them back in outputs.

- For non-interactive flows, pipe secret values via stdin (for example `printf '%s' "$NPM_TOKEN" | depot ci secrets set SECRET_NAME --from-stdin`), not command-line literals.
- Prefer interactive prompts over passing secret values as command arguments. Don't hardcode secrets or tokens in commands, scripts, workflow YAML, logs, or examples.
- Use CI secret stores for `DEPOT_TOKEN` and other credentials; pass at runtime only.
- Avoid force/non-interactive destructive flags unless explicitly requested. Before running credential-affecting commands, confirm scope (org, repo, workflow) and intended target.

## Running Workflows

```bash
# Run a workflow (auto-detects repo from git remotes, applies local uncommitted changes)
depot ci run --workflow .depot/workflows/ci.yml

# Run in a specific org (for multi-org users)
depot ci run --org <org-id> --workflow .depot/workflows/ci.yml

# Run specific jobs only
depot ci run --workflow .depot/workflows/ci.yml --job build --job test

# Trigger a run and stream its logs live
depot ci run --workflow .depot/workflows/ci.yml --job test --follow

# Run a job and connect via SSH
depot ci run --workflow .depot/workflows/ci.yml --job build --ssh

# Debug with a tmate session after step N (requires a single --job)
depot ci run --workflow .depot/workflows/ci.yml --job build --ssh-after-step 3

# Override the auto-detected repository (multiple remotes or no origin)
depot ci run --workflow .depot/workflows/ci.yml --repo owner/repo
```

The CLI auto-detects the GitHub repository from git remotes (preferring `origin`); pass `--repo owner/repo` to override. It also auto-detects uncommitted changes vs. the default branch, uploads a patch to Depot Cache, and injects a step to apply it after checkout, so your local working state runs without needing a push. Use `--ssh` / `--ssh-after-step` to start a debug session when launching a new run; use `depot ci ssh` to connect to an already-running job. Pass `--follow` (or `-f`) to stream the triggered run's logs as soon as it starts: it follows the single `--job` you request, or auto-selects when the run has one job and prompts when several are running. `--follow` cannot be combined with `--ssh` / `--ssh-after-step`.

## Dispatching Workflows

`depot ci dispatch` triggers a workflow via `workflow_dispatch` from the terminal. Inputs are validated against the workflow's declared input schema (required inputs must be supplied, typed inputs are coerced).

```bash
depot ci dispatch --repo depot/cli --workflow deploy.yml --ref main
depot ci dispatch --repo depot/cli --workflow deploy.yml --ref main \
  --input environment=staging --input dry_run=true
depot ci dispatch --repo depot/cli --workflow deploy.yml --ref main --output json
```

`--workflow` takes the workflow file's **basename** (for example `deploy.yml`), not the full path `.depot/workflows/deploy.yml`, matching GitHub's `workflow_dispatch` API convention. Required flags: `--repo <owner/repo>`, `--workflow <filename>`, `--ref <branch-or-tag>`. `--input <key>=<value>` is repeatable.

## Custom Images

Build a custom image once and reuse it across jobs to skip repeated setup steps. A custom image is a snapshot of a Depot CI sandbox, stored in your org's Depot registry, that any job in any workflow can reference by name.

### Build the image

Add the `snapshot:` keyword to a job that runs your setup steps. After the steps complete, Depot captures the sandbox state and pushes it to the Depot registry as a reusable image. Snapshot jobs first check whether the requested tags already exist: if they do, Depot skips the job and reuses the snapshot; if not, Depot runs the job and creates it.

```yaml
jobs:
  build-image:
    runs-on: depot-ubuntu-latest
    snapshot: ci-base:v1
    steps:
      - run: sudo apt-get update && sudo apt-get install -y your-tool
```

For advanced configuration, use the expanded `snapshot:` form. The `with:` block configures the underlying `depot/snapshot-action`; for example, `max-age` forces a rebuild after the configured age:

```yaml
jobs:
  build-image:
    runs-on: depot-ubuntu-latest
    snapshot:
      image-name: ci-base
      version: v1
      with:
        max-age: 5d
    steps:
      - run: sudo apt-get update && sudo apt-get install -y your-tool
```

If no version is given, Depot uses the `latest` tag. An explicit version like `v1` tags the snapshot as both `v1` and `latest`, so consumers can pin a version or follow `latest`.

### Use the image

Reference the image in any Depot CI job with the `runs-on` object syntax, specifying `size` and `image` (both required):

```yaml
jobs:
  test:
    runs-on:
      size: 2x8
      image: ci-base
    steps:
      - uses: actions/checkout@v4
```

The `image` value can be a shorthand name like `ci-base` (which Depot expands to `{orgId}.registry.depot.dev/depot/snapshots/ci-base`) or a full Depot Registry reference `{orgId}.registry.depot.dev/some-image`. It must reference an image created by a snapshot job, not an arbitrary image.

Available sizes: `2x8`, `4x16`, `8x32`, `16x64`, `32x128`, `64x256` (CPUs x RAM in GB).

**Constraints:** images get pushed to and must be pulled from the Depot registry (`registry.depot.dev`), external registries are not supported.

## Parallel Steps

Depot CI supports running steps concurrently within a single job using `parallel:` blocks, reducing job duration to the slowest branch rather than the sum of all steps. This is a Depot CI-specific feature, not compatible with GitHub Actions runners.

Use `parallel:` inside `steps:` with individual steps or `sequential:` groups. Each branch starts from the same job state; step outputs, environment variable, and `$GITHUB_PATH` changes from all branches are merged back when the block completes.

```yaml
# Run lint, typecheck, and tests concurrently
steps:
  - uses: actions/checkout@v4
  - name: Install dependencies
    run: pnpm install
  - parallel:
      - name: Lint
        run: pnpm lint
      - name: Typecheck
        run: pnpm type-check
      - name: Test
        run: pnpm test
```

Use `sequential:` inside `parallel:` to group steps that must run in order within one branch:

```yaml
- parallel:
    - sequential:
        - name: Build
          run: npm run build
        - name: Test
          run: npm test
    - name: Lint
      run: npm run lint
```

Control failure behavior with `fail-fast:`. It defaults to `true` (cancels remaining steps in the block); `false` lets all steps run to completion:

```yaml
- fail-fast: false
  parallel:
    - name: Lint
      run: pnpm lint
    - name: Typecheck
      run: pnpm type-check
```

Set `continue-on-error: true` on an individual step inside a `parallel:` block to absorb that step's failure so the group can still succeed. This differs from `fail-fast:`, which only controls whether the remaining steps are cancelled when a failure occurs, not whether the group fails:

```yaml
- parallel:
    - name: Optional check
      continue-on-error: true
      run: pnpm optional-check
    - name: Required check
      run: pnpm required-check
```

**Limitations:**

- `parallel:` cannot be nested inside another `parallel:` (use `sequential:` inside `parallel:` instead).
- Step `id` values must be unique across the entire job (including across different parallel blocks).

## Retry Steps

Automatically re-run a failed `run:` step to recover from flaky commands (network blips, transient registry errors) by adding a `retry:` key. Depot re-runs the step in place after a backoff delay and lets the job continue if a later attempt succeeds. Retries fire on any non-zero exit (no exit-code filtering) and are supported on `run:` steps only; `retry:` on a `uses:` action step is rejected at parse time, because actions carry `post:` and state machinery that is unsafe to re-run.

Shorthand form sets the number of additional attempts:

```yaml
steps:
  - run: npm ci
    retry: 3 # up to 4 total runs
```

Structured form controls backoff and delays:

```yaml
steps:
  - run: ./flaky-integration-test.sh
    retry:
      retries: 3 # additional attempts after the first run (1-10)
      backoff: exponential # 'constant' (default) or 'exponential'
      delay-seconds: 5 # base delay before the first retry (default 5)
      max-delay-seconds: 60 # cap on a single delay (default 60)
```

`retries: N` means up to `N + 1` total runs. `constant` waits `delay-seconds` before every retry; `exponential` doubles the wait each attempt (attempt _n_ waits `delay-seconds × 2^(n-1)`) up to `max-delay-seconds`. `timeout-minutes` applies per attempt (each gets a fresh budget), and `continue-on-error` is applied only after all retries are exhausted. State is not reset between attempts, since retries reuse the same sandbox, so prepend your own cleanup if a step needs a clean slate.

## Sandbox Capabilities

- **Nested virtualization**: every Depot CI sandbox exposes `/dev/kvm` with hardware virtualization enabled by default, so KVM/QEMU, Android emulator, and VM-based end-to-end tests run without extra configuration.
- **`DEPOT_JOB_URL`**: each job's environment includes `DEPOT_JOB_URL`, a direct link to the job in the Depot dashboard.
- **GitHub checks**: Depot CI automatically reports a GitHub check for each job in a workflow run.

## OIDC for Cloud Authentication

Depot CI issues a signed JWT to each job so workflows can authenticate to cloud providers (AWS, GCP, Azure) with short-lived tokens instead of static credentials. Set `permissions: id-token: write` in the workflow for the token to be issued; the issuer is `https://identity.depot.dev`. Depot injects the token-request credentials into the environment, so standard actions like `aws-actions/configure-aws-credentials` work without extra configuration.

For provider trust-policy setup, the `sub` spiffe claim format and wildcards, the full token claim reference, and migrating an existing GitHub Actions OIDC trust policy, read `references/oidc.md`.

## Running, Monitoring, and Debugging Runs

Common triage and inspection commands:

```bash
# Find recent/failed runs (defaults to queued + running)
depot ci run list
depot ci run list --status failed -n 10
depot ci run list --repo depot/api --status failed --pr 42

# Inspect a run's full workflow -> job -> attempt hierarchy
depot ci status <run-id>

# Pull logs (accepts run, job, or attempt ID; auto-selects the job if only one)
depot ci logs <run-id>
depot ci logs <run-id> --job build
depot ci logs <job-id> --follow

# Group and explain a run's failures, with a suggested fix per group
depot ci diagnose --run <run-id>

# Inspect parsed test results (Depot CI or GitHub Actions)
depot tests <attempt-id> --ci --status failed
```

Full command index, all in `references/runs-and-debugging.md`:

| Command                  | Purpose                                                                     |
| ------------------------ | --------------------------------------------------------------------------- |
| `depot ci run list`      | List runs (triage entrypoint); filter by status, repo, sha, trigger, PR     |
| `depot ci run show`      | Flat record for one run                                                     |
| `depot ci workflow list` | List workflow executions with per-job counts; filter by `--name`            |
| `depot ci workflow show` | One workflow's executions, jobs, and attempts                               |
| `depot ci status`        | Full run → workflow → job → attempt hierarchy                               |
| `depot ci logs`          | Fetch or `--follow` job logs; JSON/JSONL export                             |
| `depot ci summary`       | GitHub Actions step summary markdown for an attempt                         |
| `depot ci metrics`       | CPU and memory utilization for an attempt, job, or run                      |
| `depot ci artifacts`     | `list` run artifacts and `download` one by ID                               |
| `depot ci diagnose`      | Diagnose a failed run/workflow/job/attempt with grouped failures and fixes  |
| `depot tests`            | List parsed test results; `--ci` or `--gha`, with status/suite/test filters |
| `depot ci ssh`           | Interactive terminal into a running job's sandbox                           |
| `depot ci cancel`        | Cancel a whole run, a workflow, or a single job                             |
| `depot ci rerun`         | Re-run every terminal-state job in a workflow                               |
| `depot ci retry`         | Retry a single failed/cancelled job, or all of them with `--failed`         |

Read `references/runs-and-debugging.md` when you need a complete flag table, JSON output shape, or any command not shown in the triage examples above.

## Compatibility with GitHub Actions

Depot CI executes GitHub Actions YAML workflows. There are a few limitations where compatibility isn't 1:1. The full support and compatibility list is in `references/github-actions-compatibility.md`.

Read the compatibility reference when you need to answer or act on any of the following or similar questions:

- Whether a specific workflow-, job-, or step-level field is supported, for example `concurrency`, `jobs.<id>.environment`, `jobs.<id>.snapshot`, `jobs.<id>.container`, `jobs.<id>.services`, `jobs.<id>.strategy.matrix`, `steps[*].shell`.
- Whether a trigger event is accepted: the supported list (`push`, `pull_request`, `pull_request_target`, `pull_request_review`, `deployment_status`, `repository_dispatch`, `schedule`, `workflow_call`, `workflow_dispatch`, `workflow_run`, `merge_group`) and the GitHub-only events Depot CI rejects (for example, `release`, `issues`, `deployment`, `branch_protection_rule`).
- Which expression contexts (`github`, `env`, `vars`, `secrets`, `needs`, `strategy`, `matrix`, `steps`, `job`, `runner`, `inputs`) and functions (`always()`, `success()`, `failure()`, `cancelled()`, `case()`, `contains()`, `startsWith()`, `endsWith()`, `format()`, `join()`, `toJSON()`, `fromJSON()`, `hashFiles()`) are available.
- Which `permissions` scopes work (`actions`, `checks`, `contents`, `id-token`, `metadata`, `pull_requests`, `statuses`, `workflows`).
- Which action types run (JavaScript Node 12/16/20/24, Composite, Docker).
- Which `runs-on` Depot runner labels and sandbox sizes Depot CI supports (x86_64 and Arm only, no macOS nor Windows), and how unrecognized labels are treated.
- Diagnosing why `depot ci migrate` auto-disabled a job, stripped a trigger from `on:`, or remapped a `runs-on` label.
- Recommending workarounds for known unsupported features (cross-repo reusable workflows, fork-triggered PRs, deployment environments).

For routine migrate, run, secrets, or debug tasks that don't depend on a specific GHA feature, you don't need to load `references/github-actions-compatibility.md`.

## Directory Structure

```text
your-repo/
├── .github/
│   ├── workflows/     # Original GHA workflows (keep running)
│   └── actions/       # Local composite actions
├── .depot/
│   ├── workflows/     # Depot CI copies of workflows
│   └── actions/       # Depot CI copies of local actions
```

## Common Mistakes

| Mistake                                          | Fix                                                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| Removing `.github/workflows/` after migration    | Keep them during transition to verify Depot CI parity                                    |
| Using cross-repo reusable workflows              | Not supported yet, inline the workflow or copy it locally                                |
| Expecting branch/env variants need the dashboard | The CLI manages variants directly via `--repo`/`--env`/`--branch`/`--workflow` selectors |
| Running in the wrong org context                 | Check `depot org show`, list with `depot org list`, then switch org or pass `--org <id>` |
| Forgetting `--org` flag with multiple orgs       | Migration or run commands may miss the expected repo/workflow; specify `--org <id>`      |
| Workflows with `runs-on: windows-latest`         | Treated as `depot-ubuntu-latest`, may fail                                               |
