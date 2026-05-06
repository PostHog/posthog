---
name: debugging-ci-failures
description: >
  Debugs failing GitHub Actions CI runs for PostHog PRs, commits, and branches.
  Use when the user asks why CI is red, mentions a failing check, GitHub Actions
  run, Depot runner, workflow, job, shard, flaky test, lint failure, typecheck
  failure, snapshot diff, migration check, generated types drift, or skills
  build failure. Guides read-only inspection, failure classification, smallest
  local reproduction with hogli, and safe reporting without rerunning CI or
  posting to GitHub.
---

# Debugging PostHog CI failures

Find the first meaningful failure, classify it, reproduce the smallest useful
case locally when appropriate, and report the result. Avoid public-visible or
irreversible actions unless the user explicitly asks.

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

Determine the target in this order:

1. If the user gave a PR number, run ID, check name, or branch, use it.
2. Otherwise, infer from the current branch with
   `gh pr view --json number,headRefName,statusCheckRollup`.
3. If neither works, ask the user for a PR URL or run ID. Do not guess.

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

Extract these before classifying:

- Workflow name or file, e.g. `.github/workflows/ci-backend.yml`.
- Job name, e.g. `backend-tests (4/10)`.
- Step name, e.g. `Run pytest`.
- Failing command and the smallest useful output excerpt.

When scanning logs, search for `FAIL`, `Error`, `error:`, `assert`,
`Traceback`, `exit code`, and `##[error]`. Stop at the first failing step that
explains the run's conclusion. Keep excerpts under 40 lines.

## Classification

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

If multiple signals match, choose the most specific class. For example, prefer
codegen drift over lint, migration over typecheck, and snapshot / visual over a
generic Playwright test failure.

## Local reproduction

Run only the narrowest command that exercises the failure. If the command shape
is unclear, read `.agents/skills/hogli/SKILL.md` and `hogli <command> --help`.

| Class               | Repro guidance                                                                       |
| ------------------- | ------------------------------------------------------------------------------------ |
| code regression     | `hogli test path/to/test.py::TestClass::test_method` or `hogli test <file.test.ts>`  |
| flaky test          | Run the exact test repeatedly only if the runner supports it. Do not invent flags.   |
| lint                | Use the failing formatter/linter on touched files, e.g. `hogli format:python`.       |
| typecheck           | Run the failing checker, e.g. `pnpm --filter=@posthog/frontend typescript:check`.    |
| snapshot / visual   | Run the specific Playwright or Storybook workflow; read `playwright-test` if needed. |
| migration / schema  | `hogli migrations:check`; run migrations only if the user agrees.                    |
| codegen drift       | `hogli build:openapi`.                                                               |
| infra / runner      | No local repro. Report and stop.                                                     |
| environment / setup | Reproduce the setup step only if cheap and relevant to changed files.                |
| skills build        | `hogli lint:skills`; if that passes, `hogli build:skills`.                           |

Do NOT run `hogli test` with no arguments. Do NOT run `hogli nuke` or
`hogli dev:reset` as a shortcut. Do NOT bypass hooks with `--no-verify`.

## PostHog CI notes

- Most PostHog jobs run on `depot-ubuntu-latest` or `depot-ubuntu-latest-16`.
  Depot runs surface logs through the GitHub Actions UI / `gh run view` just
  like standard GitHub-hosted runners. There is no separate Depot console
  that agents can query in this environment.
- If a job fails before `Checkout` completes (no app code ran), classify as
  `infra / runner`. Do not propose code fixes.
- Shadow workflows are non-blocking even when red. Known shadows:
  `ci-blacksmith-shadow.yml`, `ci-test-selection-shadow.yml`. Call this out
  explicitly in the report so the user does not chase a non-blocker.
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
do not propose a code change.
