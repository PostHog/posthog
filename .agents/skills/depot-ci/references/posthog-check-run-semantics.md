# Depot CI check runs, and how GitHub scores them

PostHog-authored. Not part of the vendored upstream skill.

Two engines report on the same commit in this repo, and they are easy to confuse:

- **Depot runners** run GitHub Actions jobs from `.github/workflows/`. GitHub is still the engine, and checks come from the `github-actions` app. See the `depot-github-runners` skill.
- **Depot CI** is its own engine. It parses workflows under `.depot/workflows/`, which GitHub Actions ignores, and reports its own check runs from the `depot-code-access` app. That is what this skill covers.

Neither vendor documents any of what follows. It comes from running one job graph on both engines against the same commit and reading the check runs each posted. To re-derive it, put twin workflows in `.github/workflows/` and `.depot/workflows/`, give each job a shape from the table below, and have an `if: always()` job print `toJSON(needs)`.

## Conclusions the two engines post

| Job shape                                  | GHA `needs.result` | GHA check run               | Depot `needs.result` | Depot check run           |
| ------------------------------------------ | ------------------ | --------------------------- | -------------------- | ------------------------- |
| Plain success                              | `success`          | `success`                   | `success`            | `success`                 |
| `if: false`                                | `skipped`          | `skipped`                   | `skipped`            | `skipped`                 |
| `if:` expression that is false             | `skipped`          | `skipped`                   | `skipped`            | `skipped`                 |
| Skipped because a dependency skipped       | `skipped`          | `skipped`                   | `skipped`            | `skipped`                 |
| **Matrix that expands to zero cells**      | **`failure`**      | **none posted**             | **`skipped`**        | **`skipped`**             |
| Two cell matrix                            | `success`          | two checks, `(1)` and `(2)` | `success`            | one check, no cell suffix |
| Job-level `continue-on-error`, step fails  | `success`          | **`failure`**               | `success`            | **`failure`**             |
| Step-level `continue-on-error`, step fails | `success`          | `success`                   | `success`            | `success`                 |
| Hard failure                               | `failure`          | `failure`                   | `failure`            | `failure`                 |
| `if: always()` gate over all of the above  | `success`          | `success`                   | `success`            | `success`                 |

The engines agree everywhere except the empty matrix and the matrix check granularity.

## Two cases where the check disagrees with the run

**A job-level `continue-on-error: true` still posts a `failure` check run.** Dependents read `success`, the workflow goes green, and the check stays red. Put a required context on such a job and the merge blocks while every gate says the run passed. Prefer step-level `continue-on-error` plus an explicit verdict step, which is what `ci-backend.yml` does.

**An empty matrix is a failure on GitHub Actions, not a skip.** The job posts no check run at all, so the checks list shows nothing wrong, while every dependent reads `failure`. Depot CI calls the same job `skipped` and posts a check for it. Any job whose matrix comes from `fromJSON` of a computed value needs an `if:` guard that skips it when the list is empty, or the two engines disagree about whether the run passed.

## How GitHub scores a conclusion against a required context

- A check run that concludes `skipped` **satisfies** a required status check, and the Trunk merge queue scores it the same way. The repo already depends on this: `Build Docker image` is a required context that concludes `skipped` on most PRs, and they merge.
- A required context that **no check run ever reports** stays pending and blocks. This is the empty-matrix failure mode above, and it is also what a `paths:` filter does when it silences a whole workflow.
- Required contexts are pinned to one app. Every entry in this repo's `master` ruleset carries `integration_id: 15368`, the `github-actions` app. Read them with:

  ```bash
  gh api repos/PostHog/posthog/rulesets --jq '.[] | select(.name=="master") | .id'
  gh api repos/PostHog/posthog/rulesets/<id> \
      --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks'
  ```

  A check run posted by any other app does not satisfy a context pinned to `github-actions`, however exactly the name matches. Depot CI's app id is `219785`.

- Trunk merge queue takes its required list from GitHub branch protection by default, and can override it from the Trunk UI or from `merge.required_statuses` in `.trunk/trunk.yaml`. The trunk.yaml form matches on **name only**, with no app pinning, so a repo that sets both can have Trunk and GitHub disagree about which app's check counts. This repo sets no `merge:` block, so branch protection is the source.

## Naming

Depot names each check `<workflow name> / <job name>`. GitHub Actions names it `<job name>` alone. The workflow name is therefore part of every Depot context, and renaming a workflow renames every check it posts.

Matrix jobs differ: GitHub Actions posts one check per cell and appends the cell to the name, Depot posts one check for the whole job. Depot also posts internal expansion checks named `<file>:<job key>:_dynamicMatrix` for matrices built from `fromJSON`.

## When a check run appears

Depot creates a job's check run when it resolves the job, not when it creates the run: a job that starts gets its check in the same second as Depot's own `started_at` for the job, and a job that is skipped gets a `skipped` check when its dependencies settle. A job behind a long dependency chain therefore has no check run at all until it starts. Measured 2026-09-17 on three runs of `Backend CI on Depot` (for example run `bbtwxmr3b5`): the first job's check appeared 53 to 65 seconds after the run was created, and the gate job's check appeared 21 minutes later, when the matrix finished. GitHub Actions differs: it posts every job's check as `queued` when the run is created. A poller that treats "no check run yet" as "the run does not exist" is wrong on Depot; poll the first job in the `needs` graph to learn whether Depot picked the event up, and the gate to learn the verdict.

## Reruns

Retrying a failed Depot job created a new check run with the same name and left the failed one behind in the measured 2026-09-17 run `jb7zh5rvnk`: the retried cell got check run `105270302262` while `105262890457` stayed `completed/failure`; only `filter=all` on the check-runs API listed both. GitHub Actions does the same per attempt, which is why a superseded run can show a stale red check beside a green one of the same name. Read the latest check run per name when you script against either engine: the API's default `filter=latest` returns only the newest, and `max_by(.id)` does the same on a full listing. Two details matter when the read decides something: a GitHub Actions rerun queues a fresh check run for every job before any of them runs, so a script that wants the last verdict filters on `status == "completed"` before it takes the newest; and the check-runs API lists every pull request's checks for a head SHA, so a script that acts for one pull request filters on `pull_requests[].number` when it is present.

Depot's list can still be empty. The [check suites API](https://docs.github.com/en/rest/checks/suites) says a suite is created when code is pushed and an app usually receives one suite event per commit SHA even if that SHA is pushed to multiple branches. On commit `f786b640f2f0`, Depot's suite `97293642167` names a `posthog/rewrite-tmp/` branch and has `pull_requests: []`, while GitHub Actions suites on the same commit name PR 104868's branch and list that PR. Commit `749f24dd5b7a` shows the same split with a `-rebase-1` branch. This is consistent with the suite retaining an earlier push branch, but the suite records do not establish push order. Filtering those Depot checks by `pull_requests[].number` finds no check for the PR.

## Cancelled runs

In the following cancelled runs, an unstarted job received a `cancelled` check with `started_at` and `completed_at` set to the cancel time. A `started_at >= event time` filter kept the superseded run's check, which could be the newest one of its name. Measured 2026-09-24:

- Depot: gate check `107582798883` of cancelled workflow `x17bxd5m0z` started and completed at 09:55:14, 54 seconds after the next event and before that event's gate appeared.
- GitHub Actions: hand-off check `107604825793` of cancelled run `35990511352` started and completed at 11:05:40, after the next event (11:04:23) and 14 seconds before that event's hand-off check.

## Finding one event's Depot run

Check times and `pull_requests` did not pick out the Depot run in these cases, so the event goes into a check name. The Depot wait job's name ends with `(PR <number>, event <pull_request.updated_at>)`, and Depot renders expressions in job names into the check name. `.github/scripts/ci_backend_relay.py` builds the same name from the GitHub run's payload, reads that check, takes the Depot workflow id from its `details_url`, and reads the gate check of that workflow only. Measured 2026-09-24 on PR 105886: Depot posted check `107656013423` named `… (PR 105886, event 2026-09-24T13:33:14Z)`, and GitHub relay job `107655803961` used `EVENT_AT: 2026-09-24T13:33:14Z` and relayed a successful gate.

The newest check per name tells you the verdict. It does not tell you whether the PR can merge. A cancelled run on the same head keeps its checks, and when one of them is a required check, GitHub's merge box and Trunk keep the PR blocked until that run is rerun. `/merging-prs` has the recipe.

## pull_request_target checks

Depot can post a `pull_request_target` job's check on another pull request's head commit. A `pull_request_target` run's `github.sha` is the base branch head, so pull requests opened against the same master commit share it, and every misplaced check measured sat on a commit whose own run shared that base commit. Measured 2026-09-25 on a migration report workflow that ran on `pull_request_target`: 35 of its 42 checks sat on the wrong commit. For example, check `108123656729` on PR 106758's head `0295b92b41` links Depot workflow `ljv421dmlt`, whose run `vpg4b1kvh7` tested PR 106767's head `fb236b6c26`, and both runs had base `7af9307723`. The jobs' own writes, a check posted with an explicit `head_sha` and a comment on an explicit PR number, reached the right pull request. Post pull-request-facing results from a `pull_request` workflow, whose checks land on the right head.

## Depot CI CLI recipes

The CLI needs ids that the GitHub API does not carry. Start from a check run's `details_url`, which encodes the workflow id and job id.

```bash
# Job and workflow ids for the depot checks on a commit
gh api "repos/PostHog/posthog/commits/$SHA/check-runs?per_page=100" --paginate \
    --jq '.check_runs[] | select(.app.slug=="depot-code-access") | "\(.name)\t\(.details_url)"'

# Everything else, including the run id, from a job id
depot ci diagnose --job <job-id> -o json

depot ci logs <job-id>
depot ci retry <run-id> --workflow <workflow-id> --failed
depot ci rerun <run-id> --workflow <workflow-id>
depot ci artifacts   # artifacts do exist on Depot CI
```

One Depot run holds every workflow triggered by the same event, so `retry` and `rerun` need `--workflow` whenever more than one workflow ran. GitHub Actions splits the same event into one run per workflow.

Depot CI checks out the pull request merge ref (`refs/pull/<n>/merge`) and posts its checks against the head sha, matching GitHub Actions.

## Known gaps in Depot CI

From Depot's [compatibility page](https://depot.dev/docs/ci/compatibility), not measured here:

- Fork pull requests get no run; Depot lists support as planned. The backend router keeps them on GitHub Actions, see [Pull requests from forks](../../../../docs/published/handbook/engineering/fork-pull-requests.md).
- `environment:` is unsupported, and `uses:` cannot reference a workflow in another repository.
- `secrets.GITHUB_TOKEN` is a GitHub App installation token, not the Actions token. GitHub Packages rejects it. The rate limit it draws on is the app installation's pool, which is shared across repos and is not the per-repo Actions bucket that `monitor-github-rate-limit.yml` watches.
- Non-Depot `runs-on` labels are treated as `depot-ubuntu-latest`.
- Secrets and variables live in Depot's own store (`depot ci secrets`, `depot ci vars`), not in GitHub's.
