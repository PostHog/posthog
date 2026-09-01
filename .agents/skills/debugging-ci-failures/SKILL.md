---
name: debugging-ci-failures
description: >
  Debugs failing GitHub Actions CI runs for PostHog PRs, commits, and branches,
  and answers broad CI-health questions ("is CI red?", "is master green today?",
  "what's broken right now?"). Use when the user asks why CI is red, asks for the
  current CI or master status, or mentions a failing check, GitHub Actions run,
  Depot runner, workflow, job, shard, merge queue kick, flaky test, lint failure, typecheck
  failure, snapshot diff, migration check, generated types drift, or skills
  build failure. Start with the `hogli ci:insights` digest (cross-run CI history
  from engineering analytics), then guides read-only inspection, failure
  classification, smallest local reproduction with hogli, and safe reporting
  without rerunning CI or posting to GitHub. Running unattended as the
  "Master-red diagnosis" workflow: see references/master-red-incident.md.
---

# Debugging PostHog CI failures

Before you propose a change to CI, check [things already tried](../../../docs/internal/ci-things-already-tried.md) for the idea. It records what was measured, and why some good-sounding changes were reverted or rejected.

Find the first meaningful failure, classify it, reproduce the smallest useful
case locally when appropriate, and report the result. Avoid public-visible or
irreversible actions unless the user explicitly asks.

Always start with the `hogli ci:insights` digest. It aggregates across runs and
branches, which `gh` cannot do cheaply, and tells you whether a failure is
likely trunk-borne, gate-only, or isolated to a small set of branches. `gh` is
authoritative for one run's current state and attribution. Use the digest to
decide _what_ to inspect; use `gh` to confirm _whose_ failure it is and exactly
what failed in a given run.

This skill triages and classifies. Once a failure is confirmed flaky, hand off
to the `fixing-flaky-tests` skill, which owns local reproduction, root-cause
fixing, and N-run validation. For "who broke master" — the culprit commit and
the commit that fixed it — hand off to the `investigating-ci-failures` skill,
which owns the green/red boundary analysis. For aggregate pipeline health (is CI
getting slower, which workflow is the long pole, how long PRs take to merge),
read `diagnosing-ci-and-merge-bottlenecks`. Both are product skills under
`products/engineering_analytics/skills/`, not invocable here: read the
`SKILL.md` at that path.

## Rule out a platform outage first

GitHub Actions goes down often enough that it belongs before any log reading, and
a platform incident makes every other signal a symptom. It costs two page loads:
<https://www.githubstatus.com/> for GitHub, <https://status.depot.dev/> for the
runners. Check them whenever failures are broad — several workflows at once, a
burst of runs failing together, jobs dying before `Checkout`, or anything red
across unrelated PRs.

Report an outage as an outage, name the component, and stop recommending reruns.

## Safety rules

Do not do any of these without explicit approval in the current conversation:

- Rerun or cancel a GitHub Actions run.
- Post a GitHub comment, PR review, or issue comment through any CLI, MCP, or
  API tool.
- Push commits, force-push, rename branches, or delete branches.
- Edit `.github/workflows/` files (CI infra changes need human review).
- Merge, close, or reopen the PR.
- Accept or update snapshots.

Read-only `gh` calls and read-only GitHub tools are fine. If you need to
change local Git state, make sure it is necessary for the task and does not
overwrite unrelated work.

## Workflow

### 1. Start with CI insights (always first)

`hogli ci:insights` reads PostHog's own engineering analytics — the cross-run
failure history a single run can't show. Consult it before any raw `gh` log
archaeology.

```bash
hogli ci:insights                                # digest for the current repo + branch
hogli ci:insights search "<error or test name>"  # match a specific failure
hogli ci:insights view <ref>                     # one failure in full
hogli ci:insights view <ref> --logs              # ...plus the failing log lines
```

- Broad question ("is CI red?", "is master green today?", "what's broken right
  now?"): the no-arg digest answers directly. It gives the default-branch verdict
  (how many workflows are failing on their latest run, and which), the live
  failures grouped by state, the jobs red on trunk right now, a grouped feed of
  default-branch failures, and the PR your branch belongs to. You often do not
  need a target PR or run at all; report from the digest.
- Specific failure: run `search "<error>"` to match it before reading logs, then
  `view <ref>` on a row the digest or search printed. `--logs` prints the thinned
  failing lines from that failure's latest run, which is usually enough to
  classify without touching `gh`.

Read each row's `state` as a triage ranking:

| State                  | Means                                                                        |
| ---------------------- | ---------------------------------------------------------------------------- |
| `breaking_master`      | failing on the default branch and that job's latest run is still red         |
| `blocking_merge_queue` | failed only on merge-queue gate branches in the window                       |
| `novel_burst`          | new within a day, already spreading across branches, not on trunk yet        |
| `potentially_resolved` | hit trunk but that job's latest run is green again                           |
| `flaky`                | sporadic across two or more branches over more than a day                    |
| `pr_only`              | limited branch spread; job status may be missing or behind the failure lines |

`potentially_resolved` is a hint, not a conclusion: confirm from run data before
reporting a failure as already fixed.

`blocking_merge_queue` proves a gate failure happened in the window, not that it
still blocks landings. Check the current queue run with `gh` before reporting it
as active. Likewise, confirm `pr_only` from the current run before assigning the
failure to a PR; it is also the fallback when job status is missing or stale.

Caveats to carry into whatever you report:

- Failure grouping is pytest-only. Jest, Playwright, and cargo failures appear
  only in the digest's grouped master-failures section, never as a row with a ref.
- Every count is absolute, never a rate. Passing runs are not in the test-level
  data, so there is no denominator to quote. Job conclusions do record greens;
  the base-rate section below is how to get a real rate from them.
- A run's conclusion can lag until GitHub's `workflow_run` webhook settles it, so
  during a live incident confirm a specific run against `gh`.

If nobody has signed in on this machine, `hogli ci:insights` exits `78`. Treat
exit `78` as "no CI insights available" and fall back to the `gh`-based
inspection below — then tell the user they can run `hogli posthog:login`
once, which opens a browser and needs no API key. Do not run it yourself: it
waits on a consent screen you cannot see. Surface what you find per the Safety
rules — do not auto-apply a fix.

### 2. Find the failing run (for a specific failure)

Determine the target in this order:

1. If the user gave a PR number, run ID, check name, or branch, use it.
2. Otherwise, infer from the current branch with
   `gh pr view --json number,headRefName,statusCheckRollup`.
3. If neither works, ask the user for a PR URL or run ID. Do not guess.

**A PR kicked from the merge queue is the exception: its own checks are the
wrong target.** Trunk tests each queued PR on a `trunk-merge/pr-<n>/<uuid>`
branch holding master plus every PR queued ahead of it whose impacted targets
overlap its own. The lane script over-reports targets on purpose, so in
practice that is most of the queue. So:

- The failing run is on that branch, never on the PR's head SHA. Take it from
  the `Trunk Merge Queue` check run (`/merging-prs` step 4), not `gh pr checks`.
  The branch is ephemeral; the run and its logs stay on GitHub, and the
  warehouse keeps its jobs under that `head_branch` (query 8 in the
  `investigating-ci-failures` references).
- The PR's own checks can be green with the failing job **skipped** or
  narrowed. On the PR, path filters see only that diff and the Django suite runs
  a selected subset; on the queue branch the diff is every carried PR's and the
  full matrices always run. A docs-only PR can be kicked by a job its own CI
  never ran.
- The branch names one PR but carries many. A failure on it is not evidence
  against that PR until you find the change that caused it; the branch's other
  merge commits are the first suspects.
- In the digest this is the `blocking_merge_queue` state.

Inspect read-only:

```bash
gh pr checks <pr>
gh pr view <pr> --json statusCheckRollup
gh run view <run-id> --json jobs,conclusion,name,workflowName,url
gh run view <run-id> --log-failed
```

Use the full job log only when `--log-failed` lacks the failing command or
enough surrounding output:

```bash
gh run view <run-id> --log --job <job-id>
```

Given a run id, the `engineering-analytics-run-failure-logs` MCP tool returns
every failed job's error region with original line numbers, already thinned.
One call instead of a jobs listing plus a log download, and it works when the
job died before any test ran. It is bounded by Logs retention, so fall back to
`gh` for older runs. Given a PR number instead of a run id,
`engineering-analytics-ci-failure-logs` does the same across every run that PR
has pushed, so an earlier push's failure is still there.

Extract these before classifying:

- Workflow name or file, e.g. `.github/workflows/ci-backend.yml`.
- Job name, e.g. `backend-tests (4/10)`.
- Step name, e.g. `Run pytest`.
- Failing command and the smallest useful output excerpt.

When scanning logs, search for `FAIL`, `Error`, `error:`, `assert`,
`Traceback`, `exit code`, and `##[error]`. Stop at the first failing step that
explains the run's conclusion. Keep excerpts under 40 lines.

For test-job failures, the `trunk` MCP server's `investigate-ci-failure` tool
is a shortcut past log scanning: give it the run URL
(`https://github.com/PostHog/posthog/actions/runs/<run-id>`) and it returns
structured failing-test details — names, error messages, stdout/stderr — from
the results CI uploaded to Trunk Flaky Tests, with quarantined known-flaky
tests already filtered out. It only covers what ran and uploaded: for jobs
that died before tests (build, setup, lint), use
`engineering-analytics-run-failure-logs` or `gh run view --log`.
Authenticate once via `/mcp` → `trunk` (browser OAuth); headless environments
instead add an `Authorization: Bearer` header with a `TRUNK_API_TOKEN` org
token to the server entry in `.mcp.json`. To dig into one test's flakiness
history, hand off to `fixing-flaky-tests`, which covers the `search-test` and
`fix-flaky-test` tools.

## Classification

| Signal in the log                                                                                  | Class               | First action                                                                 |
| -------------------------------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------- |
| `AssertionError`, test diff, `FAILED test_...` in a committed test file                            | code regression     | reproduce with `hogli test <path>::<test>`                                   |
| Test failed here, passed on `master` or on rerun in the same PR                                    | flaky test          | confirm against `master` history; to fix, use `fixing-flaky-tests`           |
| `ruff`, `oxlint`, `stylelint`, `markdownlint`, `prettier` errors                                   | lint                | `hogli lint:python:fix` or `hogli format` on touched files                   |
| `mypy`, `pyright`, `tsc`, `typescript:check` errors                                                | typecheck           | run the same checker locally, not the full suite                             |
| Chromatic / Storybook / Playwright visual diff, snapshot mismatch                                  | snapshot / visual   | surface the diff URL; do NOT auto-accept snapshots                           |
| `manage.py migrate` error, `migrations:check` failure, missing migration                           | migration / schema  | `hogli migrations:check` locally                                             |
| OpenAPI schema diff, generated API types out of sync                                               | codegen drift       | `hogli build:openapi`                                                        |
| `Cannot connect`, `ECONNREFUSED`, `address already in use`, OOM, runner killed, setup step timeout | infra / runner      | get the base rate before calling it transient (below)                        |
| `startup_failure` conclusion, a job with zero recorded steps, or a log blob that 404s              | infra / runner      | no log to read; check <https://www.githubstatus.com/> and the runs around it |
| `apt-get`, `uv sync`, `pnpm install`, docker pull, setup action failures                           | environment / setup | diff `.nvmrc`, `pyproject.toml`, `package.json`, Dockerfiles                 |
| `hogli lint:skills`, `hogli build:skills` failure                                                  | skills build        | run the same `hogli` command locally                                         |
| SDK compat check, `ci-survey-sdk-check`, cross-version failure                                     | SDK compatibility   | check SDK version matrix for the affected package                            |

If multiple signals match, choose the most specific class. For example, prefer
codegen drift over lint, migration over typecheck, and snapshot / visual over a
generic Playwright test failure.

## Base rate for infra and setup failures

"Transient" is a claim about how often the job fails, so do not assert it from
one run. A job that dies before its tests run leaves no test-level evidence: no
`FAILED` line, so no fingerprint and no span, so it never appears as a row in
`broken_tests` or in the flaky-tests tool. It is still visible as a job
conclusion, which is what the digest's master-failures section groups by, and
`engineering-analytics-run-failure-logs` still returns its failing lines because
it reads by run, not by test. Start there, not from a test.

Unlike the span-derived test reads, this one can give you a real rate: the
warehouse records every job attempt, greens included, so the denominator is
honest. Query 7 in
`products/engineering_analytics/skills/investigating-ci-failures/references/investigation-queries.md`
is copy-ready; that skill also owns the wider investigation.

Read the result as:

- **Low percentage, recent hours mostly green** — transient. Report and move on.
  For a queued PR, recommend re-enqueueing rather than a code change; posting
  `/trunk merge` yourself needs approval, per the Safety rules above.
- **Recent hours entirely red** — an outage, not a flake. Say so, and stop
  telling people to retry. Check <https://www.githubstatus.com/> before
  attributing it to this repository; a platform incident makes every other
  signal a symptom.
- **A burst of runs failing together within a couple of minutes** — one shared
  cause, not several bugs. Look for a bad commit many merges inherited, or a
  GitHub dispatch overflow, which fails runs as `startup_failure` before they
  start and so leaves no log at all.
- **Steady over days** — a standing defect somebody owns. Worth a ticket even
  though each occurrence looks like noise.

## Local reproduction

Run only the narrowest command that exercises the failure. If the command shape
is unclear, read `.agents/skills/hogli/SKILL.md` and `hogli <command> --help`.

| Class               | Repro guidance                                                                       |
| ------------------- | ------------------------------------------------------------------------------------ |
| code regression     | `hogli test path/to/test.py::TestClass::test_method` or `hogli test <file.test.ts>`  |
| flaky test          | Hand off to the `fixing-flaky-tests` skill.                                          |
| lint                | Use the failing formatter/linter on touched files, e.g. `hogli format:python`.       |
| typecheck           | Run the failing checker, e.g. `pnpm --filter=@posthog/frontend typescript:check`.    |
| snapshot / visual   | Run the specific Playwright or Storybook workflow; read `playwright-test` if needed. |
| migration / schema  | `hogli migrations:check`; run migrations only if the user agrees.                    |
| codegen drift       | `hogli build:openapi`.                                                               |
| infra / runner      | No local repro. Get the base rate (above), report, and stop.                         |
| environment / setup | Reproduce the setup step only if cheap and relevant to changed files.                |
| skills build        | `hogli lint:skills`; if that passes, `hogli build:skills`.                           |

Do NOT run `hogli test` with no arguments. Do NOT run `hogli nuke` or
`hogli dev:reset` as a shortcut. Do NOT bypass hooks with `--no-verify`.

## PostHog CI notes

- Most PostHog jobs run on `depot-ubuntu-latest` or `depot-ubuntu-latest-16`.
  Depot runs surface logs through the GitHub Actions UI / `gh run view` just
  like standard GitHub-hosted runners, so read them there first.
- When a Depot runner dies mid-job, GitHub keeps no log to read: the job shows
  no steps and its log blob 404s. Depot's own dashboard keeps that job's page,
  with the verdict GitHub lost (an OOM kill, a lost runner). Open it in a
  browser through the chrome-devtools MCP. `status.depot.dev` covers the case
  where Depot itself is the outage, and the `depot-github-runners` skill owns
  runner troubleshooting beyond triage.
- If a job fails before `Checkout` completes (no app code ran), classify as
  `infra / runner`. Do not propose code fixes.
- PostHog CI frequently parallelizes the same test class across N shards
  (`backend-tests (3/10)` style). Reproduce from the specific failing test
  path, not the shard index.

## Report shape

Keep the response short. Include one likely-cause sentence and avoid deeper
speculation.

```text
Target: PR #<num> - run <run-id> (<workflow file>)
Failing job:   <job name>
Failing step:  <step name>
Command:       <failing command>
Excerpt:
  <up to 40 lines, trimmed around the failure>

Classification: <class from the table>
Shadow run:     <yes | no>
Likely cause:   <one sentence>
Local repro:    <exact command, or "none">
Next action (needs your approval):
  - <push fix | rerun job | update snapshot | none>
```

If the classification is `infra / runner` or a shadow run, say so and stop;
do not propose a code change. For `infra / runner`, include the base rate and
whether a retry is warranted.
