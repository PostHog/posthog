# Depot CI: runs, monitoring, and debugging reference

Full command surface for finding, inspecting, monitoring, debugging, and mutating CI runs. SKILL.md keeps the common examples and a command index; load this file when you need a complete flag table, JSON output shape, or a command not shown inline (`summary`, `metrics`, `artifacts`, `diagnose`, `tests`, `workflow list/show`, `cancel`, `rerun`, `retry`).

**Common flags:** every command below also accepts `--org <id>` (organization ID, required when the user belongs to multiple organizations) and `--token <token>` (Depot API token). They're omitted from the per-command tables to cut noise. Commands that emit JSON use `-o, --output json`.

## Contents

- [`depot ci run list`](#depot-ci-run-list) — list runs (triage entrypoint)
- [`depot ci run show`](#depot-ci-run-show) — flat record for one run
- [`depot ci workflow list`](#depot-ci-workflow-list) — list workflow executions with job counts
- [`depot ci workflow show`](#depot-ci-workflow-show) — one workflow's executions, jobs, attempts
- [`depot ci status`](#depot-ci-status) — full run → workflow → job → attempt hierarchy
- [`depot ci logs`](#depot-ci-logs) — fetch or follow job logs
- [`depot ci summary`](#depot-ci-summary) — step summary markdown
- [`depot ci metrics`](#depot-ci-metrics) — CPU and memory utilization
- [`depot ci artifacts`](#depot-ci-artifacts) — list and download run artifacts
- [`depot ci diagnose`](#depot-ci-diagnose) — diagnose failed runs
- [`depot tests`](#depot-tests) — list parsed test results (CI and GitHub Actions)
- [`depot ci ssh`](#depot-ci-ssh) — interactive terminal into a running job
- [`depot ci cancel`](#depot-ci-cancel) — cancel a run, workflow, or job
- [`depot ci rerun`](#depot-ci-rerun) — rerun every job in a workflow
- [`depot ci retry`](#depot-ci-retry) — retry failed/cancelled jobs
- [Debugging failed runs](#debugging-failed-runs) — the triage flow

---

## `depot ci run list`

The primary entrypoint for debugging active/recent CI activity across workflows. `depot ci run list` returns runs (one entry per triggering event); use `depot ci workflow list` instead when you want per-job-count breakdowns or to filter by workflow name.

```bash
# List runs (defaults to queued + running)
depot ci run list

# Filter by status (repeatable)
depot ci run list --status failed
depot ci run list --status finished --status failed

# Filter by repository and commit SHA prefix
depot ci run list --repo depot/api --sha abc123

# Filter by trigger event
depot ci run list --trigger workflow_dispatch

# Filter failed runs for a pull request (--pr requires --repo)
depot ci run list --repo depot/api --status failed --pr 42

# Limit number of results
depot ci run list -n 5

# Machine-readable output for tooling/agents
depot ci run list --output json
```

| Flag                  | Description                                                                          |
| --------------------- | ------------------------------------------------------------------------------------ |
| `-n <int>`            | Number of runs to return (default `50`)                                              |
| `--status <name>`     | Filter by status; repeatable: `queued`, `running`, `finished`, `failed`, `cancelled` |
| `--repo <owner/repo>` | Filter by repository                                                                 |
| `--sha <prefix>`      | Filter by commit SHA prefix                                                          |
| `--trigger <event>`   | Filter by trigger event, for example `push` or `workflow_dispatch`                   |
| `--pr <number>`       | Filter by pull request number (requires `--repo`)                                    |
| `-o, --output`        | Output format (`json`)                                                               |

---

## `depot ci run show`

Prints a flat record for one run (org, repo, status, trigger, ref, sha, head sha, timestamps). Use `depot ci status <run-id>` instead when you need the full workflow/job/attempt hierarchy.

```bash
depot ci run show <run-id>
depot ci run show <run-id> --output json
```

| Flag           | Description            |
| -------------- | ---------------------- |
| `-o, --output` | Output format (`json`) |

---

## `depot ci workflow list`

Returns workflows (one entry per workflow execution within a run, with per-job counts). Use it to filter by workflow `--name` (for example `deploy`), or to see job-count breakdowns rather than run-level status.

```bash
# List recent workflows (default 50, max 200)
depot ci workflow list

# Filter by workflow name
depot ci workflow list --name deploy

# Filter by repo, status, head SHA, and pull request
depot ci workflow list --repo depot/api --status failed --sha abc123 --pr 42

# JSON output
depot ci workflow list --output json
```

| Flag                  | Description                                                                          |
| --------------------- | ------------------------------------------------------------------------------------ |
| `-n <int>`            | Number of recent workflows to return (default `50`, max `200`)                       |
| `--name <name>`       | Filter by workflow name                                                              |
| `--repo <owner/repo>` | Filter by repository                                                                 |
| `--status <name>`     | Filter by status; repeatable: `queued`, `running`, `finished`, `failed`, `cancelled` |
| `--trigger <event>`   | Filter by trigger event, for example `push` or `workflow_dispatch`                   |
| `--sha <prefix>`      | Filter by head SHA prefix                                                            |
| `--pr <number>`       | Filter by pull request number                                                        |
| `-o, --output`        | Output format (`json`)                                                               |

---

## `depot ci workflow show`

Shows a CI workflow, including the parent run context, executions, jobs, and per-job attempt details. For each job, the output includes the latest attempt's ID, status, sandbox ID, session ID, and a ready-to-run `depot ci logs` command; if a job has multiple attempts, all are listed.

```bash
depot ci workflow show <workflow-id>
depot ci workflow show <workflow-id> --output json
```

| Flag           | Description            |
| -------------- | ---------------------- |
| `-o, --output` | Output format (`json`) |

---

## `depot ci status`

Looks up the status of a run and displays its workflows, jobs, and individual job attempts in a hierarchical view. Each attempt shows its ID, attempt number, and status, plus a ready-to-run `depot ci logs` command, a dashboard link, and (when applicable) `depot ci ssh` and log-download commands.

```bash
# Check run status (shows workflows -> jobs -> attempts hierarchy)
depot ci status <run-id>

# JSON output (full workflow/job/attempt tree, including SSH and log download metadata)
depot ci status <run-id> --output json
```

| Flag           | Description                                          |
| -------------- | ---------------------------------------------------- |
| `-o, --output` | Output as JSON instead of the hierarchical text view |

In the JSON tree, `download_available` becomes `true` and `download_command` appears once an attempt reaches `finished`. `ssh_available` and `ssh_command` appear only while an attempt is running with a sandbox.

---

## `depot ci logs`

Fetches and prints log output for a CI job. Accepts a run ID, job ID, or attempt ID; when given a run or job ID it resolves to the latest attempt automatically.

```bash
# Fetch logs (accepts run ID, job ID, or attempt ID)
depot ci logs <run-id>
depot ci logs <attempt-id>

# Specify a job when the run has multiple jobs
depot ci logs <run-id> --job test

# Disambiguate when multiple workflows share the same job key
depot ci logs <run-id> --job build --workflow ci.yml

# Follow live logs
depot ci logs <job-id> --follow
```

| Flag                   | Description                                                                                                                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--job <key>`          | Job key to select; required for multi-job runs in non-interactive contexts (piped output, `--output json`, or `--output-file`). In an interactive terminal you can pick from a list instead |
| `--workflow <path>`    | Workflow path to filter jobs (for example, `ci.yml`)                                                                                                                                        |
| `-f, --follow`         | Follow live logs as they're produced                                                                                                                                                        |
| `--timestamps`         | Prefix plain log lines with UTC timestamps                                                                                                                                                  |
| `-o, --output`         | Output format: `text` (default) or `json` (newline-delimited events)                                                                                                                        |
| `--output-file <path>` | Write a finite log export to the given file path (incompatible with `--follow`)                                                                                                             |

Combined modes:

- `--follow` streams the live attempt; pair it with `--output json` to emit newline-delimited events. JSON streaming includes `line` events plus `status` events (attempt state changes) and an `end` event with final status and line count.
- Each `line` event carries `timestamp`, `timestamp_ms`, `stream` (`stdout`/`stderr`), `step_key`, `step_id`, `step_name`, `line_number`, and `body`.
- `--output-file` cannot be combined with `--follow`. Use `--output json --output-file logs.jsonl` to download a JSONL export.
- If you pass a run or job ID that hasn't started yet, the command waits up to 30 seconds for the latest attempt to start, then streams logs as they arrive.

---

## `depot ci summary`

Fetches the GitHub Actions step summary markdown (`$GITHUB_STEP_SUMMARY`) a job attempt produced. Accepts an attempt ID or a job ID (resolves to the current/latest attempt). If no summary was authored, prints a short empty-state message and exits 0.

```bash
depot ci summary <attempt-id>
depot ci summary <job-id>
depot ci summary <attempt-id> --output json
```

| Flag           | Description                               |
| -------------- | ----------------------------------------- |
| `-o, --output` | Output format: `text` (default) or `json` |

JSON includes `org_id`, `run_id`, `workflow_id`, `job_id`, `attempt_id`, `attempt`, `job_status`, `attempt_status`, `has_summary`, `empty_reason` (for example `no_summary` or `no_attempt`), `step_count`, and `markdown`.

---

## `depot ci metrics`

Fetches CPU and memory utilization for one attempt, every attempt of a job, or every job in a run. The positional `<attempt-id>` and the `--attempt`, `--job`, `--run` flags are mutually exclusive.

```bash
# Positional attempt ID (text summary of an attempt's CPU/memory)
depot ci metrics <attempt-id>

# Equivalent with --attempt flag
depot ci metrics --attempt <attempt-id>

# Every attempt of a job
depot ci metrics --job <job-id>

# Every job and attempt in a run
depot ci metrics --run <run-id>

# Per-sample time series for one attempt (samples array only present with --attempt or positional)
depot ci metrics <attempt-id> --output json

# Per-attempt summary stats for a job or run (no samples array)
depot ci metrics --job <job-id> --output json
depot ci metrics --run <run-id> --output json
```

| Flag                     | Description                                             |
| ------------------------ | ------------------------------------------------------- |
| `--attempt <attempt-id>` | Job attempt ID (alias for the positional argument)      |
| `--job <job-id>`         | Show metrics for every attempt of the given job         |
| `--run <run-id>`         | Show metrics for every job and attempt in the given run |
| `-o, --output`           | Output format: `text` (default) or `json`               |

Run-level queries can hit a server-side sample limit; the error suggests narrowing to `--job <job-id>` or `<attempt-id>`. JSON shape depends on the form: `--attempt`/positional includes the full per-sample `samples` array; `--job` and `--run` return per-attempt summary stats without `samples`.

---

## `depot ci artifacts`

Lists CI artifact metadata and downloads one artifact by ID. Download URLs are never returned by `list`; use `artifacts download` to fetch the file.

### `depot ci artifacts list`

```bash
# List every artifact for a run
depot ci artifacts list <run-id>

# Narrow to one workflow, job, or attempt
depot ci artifacts list <run-id> --job <job-id> --output json
```

| Flag              | Description                               |
| ----------------- | ----------------------------------------- |
| `--workflow <id>` | Workflow ID to filter artifacts           |
| `--job <id>`      | Job ID to filter artifacts                |
| `--attempt <id>`  | Attempt ID to filter artifacts            |
| `-o, --output`    | Output format: `text` (default) or `json` |

JSON is `{"artifacts": [...]}` where each artifact includes `artifact_id`, `run_id`, `workflow_id`, `workflow_path`, `job_id`, `job_key`, `attempt_id`, `attempt`, `name`, `size_bytes`, and `created_at`.

### `depot ci artifacts download`

Downloads one artifact by its artifact ID. Without `--output-file`, the file is written to the artifact's original name in the current directory (control characters and path separators are sanitized to `_`). The command refuses to overwrite an existing file.

```bash
depot ci artifacts download <artifact-id>
depot ci artifacts download <artifact-id> --output-file coverage.zip
```

| Flag                   | Description                                                      |
| ---------------------- | ---------------------------------------------------------------- |
| `--output-file <path>` | Write the artifact to this file path instead of the default name |

---

## `depot ci diagnose`

Diagnoses a failed run, workflow, job, or attempt using bounded stored failure context. The command groups similar failures across attempts and, where available, surfaces a diagnosis and a possible fix for each group, with evidence lines and drill-down commands. Exactly one of `--run`, `--workflow`, `--job`, or `--attempt` is required; positional target IDs aren't accepted.

```bash
depot ci diagnose --run <run-id>
depot ci diagnose --workflow <workflow-id>
depot ci diagnose --job <job-id>
depot ci diagnose --attempt <attempt-id>
depot ci diagnose --job <job-id> --output json
```

| Flag              | Description                                                          |
| ----------------- | -------------------------------------------------------------------- |
| `--run <id>`      | Diagnose a run (mutually exclusive with the other target flags)      |
| `--workflow <id>` | Diagnose a workflow (mutually exclusive with the other target flags) |
| `--job <id>`      | Diagnose a job (mutually exclusive with the other target flags)      |
| `--attempt <id>`  | Diagnose an attempt (mutually exclusive with the other target flags) |
| `-o, --output`    | Output format: `text` (default) or `json`                            |

The text output adapts to the diagnosis state:

- **Grouped**: lists each failure group with its failure count, diagnosis, possible fix, and a small set of representative attempts and evidence lines.
- **Focused**: a single representative attempt with its error, diagnosis, possible fix, and relevant log lines.
- **Empty**: prints "No CI failures found for this target." with an optional reason.
- **Over limit**: the target spans more failed candidates than the diagnosis bounds allow; the output includes a "Narrower targets" breakdown with ready-to-run drill-down commands.

JSON includes `state` (`empty`, `grouped_failures`, `focused_failure`, or `over_limit`), `target`, `context`, `bounds`, `failure_groups` (with `diagnosis`, `possible_fix`, and representative attempts), `representative_attempts`, `next_commands`, and `over_limit_breakdown` when over limit.

---

## `depot tests`

Lists parsed test results. This is a top-level command (`depot tests`, not `depot ci tests`). Choose exactly one backend: `--ci` or `--gha`.

- **`--ci`**: Depot CI results. The ID may be a run, job, or attempt ID; run and job IDs resolve to the latest matching attempt, matching `depot ci logs`.
- **`--gha`**: GitHub Actions results. The ID may be a GitHub Actions job ID or the stored Depot GitHub job row ID.

```bash
depot tests <attempt-id> --ci
depot tests <run-id> --ci --job test
depot tests <github-job-id> --gha --status failed
depot tests <attempt-id> --ci --output json
```

| Flag                 | Description                                                                             |
| -------------------- | --------------------------------------------------------------------------------------- |
| `--ci`               | Read Depot CI test results                                                              |
| `--gha`              | Read GitHub Actions test results                                                        |
| `--job <key>`        | Depot CI job key to select when the ID is a run (`--ci` only)                           |
| `--workflow <path>`  | Depot CI workflow path to filter jobs, for example `ci.yml` (`--ci` only)               |
| `--status <name>`    | Test status to include: `unknown`, `passed`, `failed`, `errored`, `skipped`; repeatable |
| `--suite <name>`     | Test suite name to include                                                              |
| `--test <name>`      | Test case name to include                                                               |
| `--class <name>`     | Test class name to include                                                              |
| `--file <name>`      | Source filename to include                                                              |
| `--page-size <n>`    | Results per page (default `100`, max `500`)                                             |
| `--page-token <tok>` | Token to fetch the next page                                                            |
| `--output`           | Output format: `auto` (default), `table`, or `json` (no `-o` shorthand)                 |

`--job` and `--workflow` can only be used with `--ci`.

---

## `depot ci ssh`

Opens an interactive terminal session to the sandbox running a CI job. Accepts a run ID or job ID. If the job hasn't started yet, the command waits up to 5 minutes for the sandbox to be provisioned. Use `--ssh` / `--ssh-after-step` on `depot ci run` instead to start a debug session when launching a new run.

```bash
# Connect directly using a job ID
depot ci ssh <job-id>

# Connect to a specific job in a run
depot ci ssh <run-id> --job build

# Auto-select job when there's only one
depot ci ssh <run-id>

# Print SSH connection details for automation
depot ci ssh <run-id> --info --output json
```

| Flag           | Description                                           |
| -------------- | ----------------------------------------------------- |
| `--job <key>`  | Job key to connect to (required for multi-job runs)   |
| `--info`       | Print SSH details instead of connecting interactively |
| `-o, --output` | Output format for `--info` (`json`)                   |

`--info --output json` returns `host` (`exec.depot.dev`), `sandbox_id`, `session_id`, and a ready-to-run `ssh_command`.

---

## `depot ci cancel`

Cancels a queued or running run, an entire workflow (all its jobs), or a single job. With no scope flag the entire run is cancelled. `--workflow` and `--job` are mutually exclusive; with `--job` the CLI resolves the containing workflow from run status automatically. Runs, workflows, or jobs already in a terminal state (finished, failed, cancelled) cannot be cancelled and return an error.

```bash
# Cancel an entire run (and every workflow and job within it)
depot ci cancel <run-id>

# Cancel one workflow within the run (and all its jobs)
depot ci cancel <run-id> --workflow <workflow-id>

# Cancel a single job (workflow is resolved automatically)
depot ci cancel <run-id> --job <job-id>

# JSON output
depot ci cancel <run-id> --output json
```

| Flag              | Description                                                                |
| ----------------- | -------------------------------------------------------------------------- |
| `--workflow <id>` | Workflow ID to cancel (mutually exclusive with `--job`; omit both for run) |
| `--job <id>`      | Job ID to cancel (mutually exclusive with `--workflow`; omit both for run) |
| `--output json`   | Output the RPC response as JSON                                            |

---

## `depot ci rerun`

Re-runs every job in a workflow that has reached a terminal state, creating a new attempt for each. For single-workflow runs the CLI resolves the workflow automatically; for multi-workflow runs pass `--workflow <id>`. Rerunning a workflow that is still running returns a precondition error: cancel it first.

```bash
# Rerun the (single) workflow in a run
depot ci rerun <run-id>

# Rerun a specific workflow in a multi-workflow run
depot ci rerun <run-id> --workflow <workflow-id>

# JSON output
depot ci rerun <run-id> --output json
```

| Flag              | Description                                                              |
| ----------------- | ------------------------------------------------------------------------ |
| `--workflow <id>` | Workflow ID to rerun (required when the run contains multiple workflows) |
| `--output json`   | Output the RPC response as JSON                                          |

---

## `depot ci retry`

Retries a single failed or cancelled job with `--job <job-id>`, or every failed/cancelled job in a workflow with `--failed`. Exactly one of `--job` or `--failed` must be set. With `--job` the containing workflow is resolved automatically; with `--failed` on a multi-workflow run, `--workflow <id>` is required. Each retry creates a new attempt; previous attempts remain visible in `depot ci status`.

```bash
# Retry a single job
depot ci retry <run-id> --job <job-id>

# Retry every failed/cancelled job in the (single) workflow
depot ci retry <run-id> --failed

# Retry every failed/cancelled job in a specific workflow
depot ci retry <run-id> --failed --workflow <workflow-id>

# JSON output
depot ci retry <run-id> --job <job-id> --output json
```

| Flag              | Description                                                                        |
| ----------------- | ---------------------------------------------------------------------------------- |
| `--job <id>`      | Job ID to retry (mutually exclusive with `--failed`)                               |
| `--failed`        | Retry every failed/cancelled job in the workflow (mutually exclusive with `--job`) |
| `--workflow <id>` | Workflow ID; required with `--failed` when the run has multiple workflows          |
| `--output json`   | Output the RPC response as JSON                                                    |

---

## Debugging failed runs

A typical triage flow:

```bash
# Find failed runs
depot ci run list --status failed -n 10

# Pull logs directly (auto-selects job if only one)
depot ci logs <run-id>

# Specify job when there are multiple
depot ci logs <run-id> --job build

# Group and explain the failures, with a suggested fix per group
depot ci diagnose --run <run-id>

# Inspect the full workflow/job/attempt hierarchy when needed
depot ci status <run-id>

# Inspect produced test results or download artifacts for more context
depot tests <attempt-id> --ci --status failed
depot ci artifacts list <run-id>
```

Use `--output json` on `depot ci run list` (and the other commands here) for machine-readable output.
