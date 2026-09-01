# Depot CI check runs, and how GitHub scores them

PostHog-authored. Not part of the vendored upstream skill.

Two engines report on the same commit in this repo, and they are easy to confuse:

- **Depot runners** run GitHub Actions jobs from `.github/workflows/`. GitHub is still the engine, and checks come from the `github-actions` app. See the `depot-github-runners` skill.
- **Depot CI** is its own engine. It parses workflows under `.depot/workflows/`, which GitHub Actions ignores, and reports its own check runs from the `depot-code-access` app. That is what this skill covers.

Everything below was measured, not read from docs. Two twin workflows ran an identical job graph on both engines against the same commit ([probe PR](https://github.com/PostHog/posthog/pull/92542)).

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

## Two traps that bite on both engines

**A job-level `continue-on-error: true` still posts a `failure` check run.** Dependents read `success`, the workflow goes green, and the check stays red. Put a required context on such a job and the merge blocks while every gate says the run passed. Prefer step-level `continue-on-error` plus an explicit verdict step, which is what `ci-backend.yml` does.

**An empty matrix is a failure on GitHub Actions, not a skip.** The job posts no check run at all, so the checks list shows nothing wrong, while every dependent reads `failure`. Depot CI calls the same job `skipped` and posts a check for it. Any job whose matrix comes from `fromJSON` of a computed value needs an `if:` guard that skips it when the list is empty, or the two engines disagree about whether the run passed.

## How GitHub scores a conclusion against a required context

- A check run that concludes `skipped` **satisfies** a required status check. Production evidence: `Build Docker image` concludes `SKIPPED` on merged PRs [92414](https://github.com/PostHog/posthog/pull/92414), [92402](https://github.com/PostHog/posthog/pull/92402), [92396](https://github.com/PostHog/posthog/pull/92396) and [92372](https://github.com/PostHog/posthog/pull/92372). All four merged, and all four went through the Trunk merge queue, so Trunk scores it the same way.
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

## Reruns

Depot updates the existing check run in place. Measured by retrying one failed job: the check run kept id `99890906312` and only its timestamps moved. GitHub Actions instead creates a fresh check run per attempt and leaves the old one behind, which is why a superseded GitHub Actions run can show a stale red check next to a green one for the same name.

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

- Fork pull requests are unsupported. Depot lists support as planned.
- `environment:` is unsupported, and `uses:` cannot reference a workflow in another repository.
- `secrets.GITHUB_TOKEN` is a GitHub App installation token, not the Actions token. GitHub Packages rejects it. The rate limit it draws on is the app installation's pool, which is shared across repos and is not the per-repo Actions bucket that `monitor-github-rate-limit.yml` watches.
- Non-Depot `runs-on` labels are treated as `depot-ubuntu-latest`.
- Secrets and variables live in Depot's own store (`depot ci secrets`, `depot ci vars`), not in GitHub's.
