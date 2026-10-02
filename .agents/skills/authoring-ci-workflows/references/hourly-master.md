# The hourly master lane

The merge queue's `trunk-merge/**` run tests every commit before it lands, so re-running a heavy suite on the master push tests a commit that CI already covered.
Those suites skip `push` and take their master coverage and Trunk flaky-test baseline from an hourly `schedule:` instead.

Crons are offset so the runs do not all fire at once:

| Workflow                            | Minute |
| ----------------------------------- | ------ |
| `ci-frontend.yml`                   | 7      |
| `ci-nodejs.yml`                     | 13     |
| `ci-backend.yml`                    | 23     |
| `ci-dagster.yml`                    | 33     |
| `ci-python.yml`                     | 43     |
| `ci-mcp.yml`                        | 53     |
| `ci-backend-update-test-timing.yml` | 17     |

Adding a seventh suite: pick an unused minute, add the row, and keep the gap at ten minutes.
`ci-backend-update-test-timing.yml` is one small job that merges the hourly runs' artifacts, so it does not need the ten-minute gap.

## Concurrency

Give the cron its own concurrency group.
`cancel-in-progress` is false outside pull requests, but GitHub keeps at most one pending run per group.
A newer run replaces an older pending one.
If a cron shares the ref group with master pushes, it holds that group while running and newer pushes discard older pending per-commit checks.

```yaml
group: ${{ github.workflow }}-${{ github.event_name == 'schedule' && 'scheduled' || github.head_ref || github.ref }}
```

That keeps hourly runs queueing behind each other and leaves push behavior untouched.
`ci-backend.yml` instead keys pushes per SHA, so pushes never share a group with the cron.
Prefer the `scheduled` key when the push lane still runs per-commit work: per-SHA pushes also give up burst deduplication.

## Paths and alerting

Skip the paths filter on `schedule`, and give every consumed output a `|| 'true'` default.
A cron provides no `before` commit or distinct base, so the action can fall back to the last commit alone.
A docs-only commit then narrows the hourly run to nothing and reports green without testing the suite.
Use `if: github.event_name != 'push' && github.event_name != 'schedule'`.
Any step that reads a filter output needs the same schedule guard.
`ci-dagster.yml`'s `build-matrix` must obey it or the matrix becomes empty.

The master-red alerter reads run completions; a dropped cron becomes unreadable rather than paging.
Add converted workflows to `SCHEDULED_GATING_WORKFLOWS` in `ci-alerts-devex.yml` so failures continue paging.

## Backend engine ownership

GitHub owns both master pushes and scheduled Backend CI events.
`CI_BACKEND_DEPOT_MASTER_LANES` selects new events: empty or `github` keeps both lanes on GitHub, `schedule` delegates only crons, and `all` delegates both.
The PR and merge-queue percentage switches remain independent.

The `changes` job persists an owner receipt before releasing work.
`master-depot` persists the dispatch acknowledgment and workflow binding before the Depot worker can authorize itself.
The worker checks out the receipt's SHA and uses its event and cron, even if the dispatched workflow came from a newer master commit.
Depot has no independent push or schedule trigger.
It never reads this switch to choose ownership.

The canonical GitHub job republishes artifacts with their original names and retention, including failed-run diagnostics.
The GitHub-hosted schema mirror still supplies fork PRs' cache entries.
The required GitHub Actions gate fails on a missing, cancelled, skipped, or failed master relay.

Changing the switch affects only new owners.
Existing receipts retain their engine across rollback and reruns.
A rerun without a receipt or known dispatch outcome fails closed; recover the original run instead of dispatching another.

Keep activation separate from workflow changes.
Before enabling `schedule`, verify token permissions, both cron variants, artifact consumers, caches, Trunk attribution, alerts, and each API rate-limit bucket with authorized live trials.
Enable `all` only after the schedule proofs and master-push migration replay, deploy-consumer, and peak-hour API checks pass.
