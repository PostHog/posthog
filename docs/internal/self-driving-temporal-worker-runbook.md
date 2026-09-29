# Self-driving Temporal worker runbook

How to operate the `temporal-worker-self-driving` fleet, and how to check that the inbox ranking sweep runs on it.

## What the fleet is

The fleet is a dedicated Temporal worker for low-priority self-driving background jobs.
It keeps heavy, memory-hungry work off the video-export fleet, which runs the rest of Signals.

| Item        | Value                                                                             |
| ----------- | --------------------------------------------------------------------------------- |
| Release     | `temporal-worker-self-driving` in the `PostHog/charts` repo                       |
| Owner team  | `signals`                                                                         |
| Task queue  | `self-driving-task-queue` (`settings.SELF_DRIVING_TASK_QUEUE`)                    |
| Regions     | dev, prod-us, and prod-eu                                                         |
| Pods        | 2 fixed pods, no autoscaling                                                      |
| Resources   | Requests `cpu: 1` and `memory: 4Gi`. Limit `memory: 6Gi`.                         |
| Worker env  | `TEMPORAL_TASK_QUEUE` and `SELF_DRIVING_TASK_QUEUE` are `self-driving-task-queue` |
| App secrets | None. The fleet has no worker secret.                                             |

The worker starts with `start_temporal_worker --task-queue self-driving-task-queue`.
`WORKFLOWS_DICT` in `posthog/management/commands/start_temporal_worker.py` maps that queue to `SELF_DRIVING_WORKFLOWS` and `SELF_DRIVING_ACTIVITIES` from `products/signals/backend/temporal/__init__.py`.

## What runs on it

Only the inbox ranking scoring sweep runs on this fleet:

- Workflow `inbox-ranking-scoring-sweep` (`InboxRankingScoringWorkflow`).
- Activity `score_inbox_reports_activity`.

Both live in `products/signals/backend/ranking/sweep.py`.
The video-export fleet does not register them.
All other Signals workflows (ingestion, grouping, summaries, scouts) stay on the video-export fleet.

## The ranking sweep schedule

`create_inbox_ranking_scoring_schedule` in `products/signals/backend/ranking/schedule.py` registers the schedule.
The `schedule_temporal_workflows` management command calls it on each Django deploy.

| Setting           | Value                                                                 |
| ----------------- | --------------------------------------------------------------------- |
| Schedule ID       | `inbox-ranking-scoring-sweep-schedule`                                |
| Task queue        | `settings.SELF_DRIVING_TASK_QUEUE`, default `self-driving-task-queue` |
| Interval          | `INBOX_RANKING_SCORING_INTERVAL_MINUTES`, default 15                  |
| Overlap policy    | `SKIP`                                                                |
| Execution timeout | One interval                                                          |
| Activity timeout  | 10 minutes, with one attempt and no retry                             |
| Time budget       | 8 minutes. The pass starts no new team after this budget.             |

A deploy keeps the live schedule state.
If an operator pauses the schedule, the next deploy does not resume it.

`INBOX_RANKING_SCORING_ENABLED` gates the work, not the schedule.
The fleet sets it to `"false"`, so each tick logs `inbox_ranking_sweep_skipped` with `skipped_reason="disabled"` and returns.
Scoring stays off until [#108197](https://github.com/PostHog/posthog/issues/108197) is resolved.

## Deploys

The `selfDriving` path filter in `.github/workflows/container-images-cd.yml` builds the worker image.
A merge to master that touches those paths sends a `commit_state_update` dispatch to `PostHog/charts` for the `temporal-worker-self-driving` release.

The filter shares `products/signals/backend/**` and `products/signals/skills/**` with the `videoExport` filter.
A change to Signals backend code deploys both fleets.
A change to `posthog/settings/temporal.py` deploys only the self-driving fleet.

## Checks after a deploy or cut-over

Do these checks in each region.

1. Make sure that the fleet polls the queue.
   Run `temporal task-queue describe --task-queue self-driving-task-queue`.
   The output must show pollers from the `temporal-worker-self-driving` pods.
2. Make sure that the schedule targets the new queue.
   Run `temporal schedule describe --schedule-id inbox-ranking-scoring-sweep-schedule`.
   The action task queue must be `self-driving-task-queue`.
3. Make sure that ticks complete on the new fleet.
   In the Temporal UI, filter by workflow type `inbox-ranking-scoring-sweep`.
   Each recent run must show task queue `self-driving-task-queue` and status `Completed`.
4. Make sure that the pod logs show each tick.
   Search the fleet logs for `inbox_ranking_sweep_skipped`, `inbox_ranking_sweep_started`, and `inbox_ranking_sweep_finished`.
   The `started` and `finished` events carry `peak_rss_mb`.
5. Make sure that no other Signals workflow moved.
   `temporal task-queue describe --task-queue video-export-task-queue` must still show pollers.
   Scout, grouping, and summary workflows must still run on `video-export-task-queue`.
6. Make sure that no video-export pod restarts with `OOMKilled` after the cut-over.

## Common operations

**Pause the sweep.**
Run `temporal schedule toggle --schedule-id inbox-ranking-scoring-sweep-schedule --pause --reason "<why>"`.
Use `--unpause` to resume it.

**Run one tick now.**
Run `temporal schedule trigger --schedule-id inbox-ranking-scoring-sweep-schedule`.

**Turn scoring on.**
Set `INBOX_RANKING_SCORING_ENABLED` to `"true"` on the charts release for one region.
Watch `peak_rss_mb` and pod memory against the 6Gi limit before the next region.

**Move a workload to this fleet.**

1. Add its workflow and activities to `SELF_DRIVING_WORKFLOWS` and `SELF_DRIVING_ACTIVITIES`.
2. Remove them from the Signals `WORKFLOWS` and `ACTIVITIES` lists.
3. Start the workflow or its schedule on `settings.SELF_DRIVING_TASK_QUEUE`.
4. Update `test_module_integrity.py` and `test_start_temporal_worker.py`.
5. Add a worker secret to the charts release if the workload needs app-specific keys.

## Troubleshooting

**Runs stay in `Running` with no activity progress.**
No worker polls `self-driving-task-queue` in that region.
Check the pod status of the charts release, then run check 1.

**Runs show `TimedOut` each tick.**
The pass took longer than the activity timeout.
The next tick continues from where the last one stopped, because the vector comparison finds the unscored reports again.
If this happens on each tick, lower `INBOX_RANKING_SCORING_MAX_REPORTS_PER_TICK`.

**Pods restart with `OOMKilled`.**
Compare `peak_rss_mb` in the last `inbox_ranking_sweep_started` log with the 6Gi limit.
A killed pass logs no `finished` event.
Lower `INBOX_RANKING_SCORING_BATCH_SIZE` or pause the schedule.

**Local development.**
With `DEBUG` on, every queue collapses to `development-task-queue`.
The local worker runs the sweep with all other workflows.
