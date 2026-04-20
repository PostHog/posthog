---
name: debug-ci-failure
description: >
  Triage a failing GitHub Actions CI run on a PostHog PR or commit. Use when
  the user asks to debug a red check, a CI failure, a Depot job, a failing
  workflow, or "why is CI red". Covers identifying the failed job and step,
  classifying the failure, reproducing it locally with hogli, and reporting
  findings back without posting to GitHub or rerunning CI.
---

# Debugging a failing PostHog CI run

A focused procedure for triaging a red CI run on a PostHog PR. Goal: identify
the failure, classify it, reproduce the smallest possible local repro with
`hogli`, and report back. Never take public-visible or irreversible actions
without explicit user approval.

## Safety rules (read first)

Do NOT do any of the following without the user explicitly asking in this
session:

- Rerun a failed job (`gh run rerun`, MCP equivalents).
- Cancel an in-progress run (`gh run cancel`).
- Post a GitHub comment, PR review, or issue comment (`gh pr comment`,
  `gh pr review`, `gh issue comment`, `mcp__github__add_issue_comment`,
  `mcp__github__pull_request_review_write`, etc.). Draft text locally if the
  user asks — do not submit it.
- Push a fix commit, force-push, rename or delete a branch.
- Edit `.github/workflows/` files (CI infra changes need human review).
- Merge, close, or reopen the PR.

Read-only `gh` and GitHub MCP calls (read, list, view) are fine at any time.

## Inputs

Determine the target in this order:

1. If the user gave a PR number, run ID, check name, or branch — use it.
2. Else, infer from the current branch:
   `gh pr view --json number,headRefName,statusCheckRollup`.
3. If neither works, ask the user for a PR URL or run ID. Do not guess.

## Inspect the run (read-only)

Prefer GitHub MCP when available; fall back to `gh`.

```bash
# High-level status
gh pr checks <pr>
gh pr view <pr> --json statusCheckRollup

# Full run metadata
gh run view <run-id> --json jobs,conclusion,name,workflowName,url

# Failed steps only (start here — smallest useful log)
gh run view <run-id> --log-failed

# Full log for one job (only if --log-failed is insufficient)
gh run view <run-id> --log --job <job-id>
```

MCP equivalents: `mcp__github__pull_request_read`, `mcp__github__get_commit`,
`mcp__github__list_pull_requests`. Use them instead of `gh` if they reduce
round-trips; the content is the same.

When scanning logs, grep for `FAIL`, `Error`, `error:`, `assert`,
`Traceback`, `exit code`, `##[error]`, and stop at the first failing step.
Keep the excerpt to 40 lines or fewer.

## Locate the failing unit

Always extract these four fields before doing anything else:

1. Workflow file, e.g. `.github/workflows/ci-backend.yml`.
2. Job name, e.g. `backend-tests (4/10)`.
3. Step name, e.g. `Run pytest`.
4. The failing command and its output excerpt.

If you cannot find all four, keep reading the log — do not classify yet.

## Classify the failure

Pick exactly one class using the first matching signal.

| Signal in the log                                                        | Class               | First action                                                         |
| ------------------------------------------------------------------------ | ------------------- | -------------------------------------------------------------------- |
| `AssertionError`, test diff, `FAILED test_...` in a committed test file  | code regression     | reproduce with `hogli test <path>::<test>`                           |
| Test failed here, passed on `master` or on rerun in the same PR          | flaky test          | confirm against `master` history; do not "fix" without user approval |
| `ruff`, `oxlint`, `stylelint`, `markdownlint`, `prettier` errors         | lint                | `hogli lint:python:fix` or `hogli format` on touched files           |
| `mypy`, `pyright`, `tsc`, `typescript:check` errors                      | typecheck           | run the same checker locally, not the full suite                     |
| Chromatic / Storybook / Playwright visual diff, snapshot mismatch        | snapshot / visual   | surface the diff URL; do NOT auto-accept snapshots                   |
| `manage.py migrate` error, `migrations:check` failure, missing migration | migration / schema  | `hogli migrations:check` locally                                     |
| OpenAPI schema diff, generated API types out of sync                     | codegen drift       | `hogli build:openapi`                                                |
| `Cannot connect`, `ECONNREFUSED`, OOM, runner killed, setup step timeout | infra / runner      | treat as transient; report, do not fix                               |
| `apt-get`, `uv sync`, `pnpm install`, docker pull, setup action failures | environment / setup | diff `.nvmrc`, `pyproject.toml`, `package.json`, Dockerfiles         |
| `hogli lint:skills`, `hogli build:skills` failure                        | skills build        | run the same `hogli` command locally                                 |
| SDK compat check, `ci-survey-sdk-check`, cross-version failure           | SDK compatibility   | check SDK version matrix for the affected package                    |

If two signals match, prefer the more specific class (codegen drift over
lint, migration over typecheck, etc.).

## Reproduce locally (smallest command)

Pick the narrowest command that exercises the failure. Never fall back to
running the whole suite.

| Class               | Command                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------- |
| code regression     | `hogli test path/to/test.py::TestClass::test_method` (or `hogli test <file.test.ts>`)       |
| flaky test          | same as code regression, looped: `hogli test <path> --count 20` if supported                |
| lint                | `hogli format:python <paths>` / `hogli format:js <paths>` / `hogli format:markdown <paths>` |
| typecheck           | `pnpm --filter=@posthog/frontend typescript:check` (TS) or the failing file's checker       |
| snapshot / visual   | `hogli test <playwright.spec.ts>` for Playwright; see `playwright-test` skill               |
| migration / schema  | `hogli migrations:check` (then `hogli migrations:run` only if the user agrees)              |
| codegen drift       | `hogli build:openapi`                                                                       |
| infra / runner      | none — report and stop                                                                      |
| environment / setup | reproduce the failing setup step locally only if it is cheap; otherwise report              |
| skills build        | `hogli lint:skills` then `hogli build:skills`                                               |

Do NOT run `hogli test` with no arguments. Do NOT run `hogli nuke` or
`hogli dev:reset` as a shortcut. Do NOT `--no-verify` a commit.

Test path shortcuts:

- Python test: `hogli test path/to/test.py::TestClass::test_method`
- Jest: `hogli test path/to/file.test.ts`
- Playwright: `hogli test path/to/file.spec.ts`
- Watch: add `--watch`. Changed files: `hogli test --changed`.

See `.agents/skills/hogli/SKILL.md` for the full command set.

## Depot-specific notes

- Most PostHog jobs run on `depot-ubuntu-latest` or `depot-ubuntu-latest-16`.
  Depot runs surface logs through the GitHub Actions UI / `gh run view` just
  like standard GitHub-hosted runners — there is no separate Depot console
  that agents can query in this environment.
- If a job fails before `Checkout` completes (no app code ran), classify as
  `infra / runner`. Do not propose code fixes.
- Shadow workflows are non-blocking even when red. Known shadows:
  `ci-blacksmith-shadow.yml`, `ci-test-selection-shadow.yml`. Call this out
  explicitly in the report so the user does not chase a non-blocker.
- PostHog CI frequently parallelizes the same test class across N shards
  (`backend-tests (3/10)` style). Reproduce from the specific failing test
  path, not the shard index.

## Report back in this shape

Keep the response under 40 lines. One sentence of likely cause, no deeper
speculation.

```text
Target: PR #<num> — run <run-id> (<workflow file>)
Failing job:   <job name>
Failing step:  <step name>
Command:       <failing command>
Excerpt:
  <up to 40 lines, trimmed around the failure>

Classification: <class from the table>
Shadow run:     <yes | no>
Likely cause:   <one sentence>
Local repro:    <exact hogli command>
Next action (needs your approval):
  - <push fix | rerun job | update snapshot | none>
```

If the classification is `infra / runner` or a shadow run, say so and stop —
do not propose a code change.

## Future `hogli` support (not blocking v1)

Nice-to-have commands that would let this skill collapse several steps. Do
not implement as part of using this skill:

- `hogli ci:failing <pr>` — print the job / step / command / excerpt block.
- `hogli ci:repro <run-id>` — print the suggested local reproduction command.
- `hogli ci:classify <run-id>` — return the failure class for a run.
- `hogli ci:shadow-check <run-id>` — flag whether the red check is from a
  non-blocking shadow workflow.
