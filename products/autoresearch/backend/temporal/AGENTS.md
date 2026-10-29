# Temporal workflows

The scheduled half of autoresearch. Four workflows and their activities, registered on `settings.AUTORESEARCH_TASK_QUEUE` by `start_temporal_worker`, which imports `WORKFLOWS` and `ACTIVITIES` from `__init__.py`.

Scoring, validation and training live in `../inference/`, `../evaluation/`, and `../training/` — the same functions the management commands and the API reach — and the activities call them, so the scheduled path cannot drift from the headless one. What stays here is the sweep's own logic: discovery (cadence, rollout, creator access) and the kickoff's eligibility gates, research schedule and row lock.

## What lives here

- `workflows.py`
  - `AutoresearchCoordinatorWorkflow` (`autoresearch-coordinator`) — the daily tick. Loads active pipelines (`activity_load_active_pipelines`) and runs inference, training kickoff, and validation per pipeline, with at most `CoordinatorWorkflowInput.max_concurrency` pipelines in flight (`DEFAULT_COORDINATOR_CONCURRENCY`, 4). After every champion has scored, it runs `activity_run_shadow_scoring` per completed champion run, under the same bound. With `CoordinatorWorkflowInput.catch_up` it runs a catch-up sweep, which scores only.
  - `activity_fail_lost_inference_runs` — fails the scheduled runs of one pipeline and date that are still `running` (`fail_lost_scheduled_runs()` in `../inference/failures.py`). The coordinator starts it when an inference child ends in a `ChildWorkflowError`, which covers a failed last attempt and the workflow timeout. A child that did not start (its id is already running) does not trigger it, so a live run stays open. `activity_run_inference` records `metrics["workflow_run_id"]` on a scheduled run, and the cleanup fails only the rows of the failed child's run id, so a catch-up child that started for the same date keeps its live row.
  - `AutoresearchInferenceWorkflow` (`autoresearch-inference`) — `activity_run_inference` for one pipeline. The activity reads the current champion itself, so a retry after a mid-scoring promotion scores with the new one. The sweep sets `defer_shadows`, so the activity scores the champion only.
  - `activity_run_shadow_scoring` — scores the shadow set against the people a champion's completed run scored (`score_shadow_set_for_run()` in `../inference/scoring.py`). It takes only the run id. It has one attempt, because a retry would open a second shadow run per model, and its failure never fails the champion's run or counts as a pipeline error.
  - `AutoresearchValidationWorkflow` (`autoresearch-validation`) — `activity_run_validation` for one pipeline.
  - `activity_kickoff_training` — launches a training run for a pipeline that is due.
  - `AutoresearchPropertyCleanupWorkflow` (`autoresearch-property-cleanup`) — `activity_remove_person_property` removes a pipeline's output person property from persons (`../inference/person_property.py`), then runs a reconcile pass an hour later for scores that were still ingesting during the first pass. The run row stays `running` until the reconcile pass ends, and a retry adds to the count on the row. When the activity runs out of retries, the workflow fails the run with `activity_fail_cleanup_run`. The facade starts it, not the coordinator, with one workflow id per cleanup request.

  Each workflow has a typed input/result dataclass pair (`InferenceWorkflowInput` / `InferenceWorkflowResult`, and so on). Activities are named with a `autoresearch-<workflow>.<activity>` convention.

- `schedule.py`
  `create_autoresearch_daily_schedule()` registers schedule `autoresearch-daily-coordinator` driving workflow id `autoresearch-coordinator` at 02:00 UTC, and schedule `autoresearch-catch-up-coordinator` driving workflow id `autoresearch-coordinator-catch-up` at 08:00, 14:00 and 20:00 UTC with `catch_up=True`.
  The catch-up fires more than once, because an inference child can fail up to `INFERENCE_WORKFLOW_TIMEOUT` after it starts, and the daily sweep starts children until its own timeout. Each tick retries the runs lost since the tick before it, so a pipeline gets at most three retries a day.
  The catch-up has its own workflow id. The daily coordinator marks its date `running` in the cache before discovery and `done` after its last scoring, kickoff, validation and shadow step (`activity_mark_daily_sweep`, key `daily_sweep_key()`). A catch-up tick lists no pipelines while the marker of its date reads `running`, so the two sweeps never run past one concurrency bound together. The next tick tries again. The `running` marker expires with `COORDINATOR_TIMEOUT`, so a coordinator that dies without marking `done` holds the catch-up back no longer than it could still run.
  Overlap policy is **SKIP** — a tick that is still running causes the next one to be dropped rather than queued, so a slow day cannot pile up a backlog of duplicate scoring runs.
  An update keeps the schedule's live state, so a deploy does not resume a schedule an operator paused.
  The queue defaults to `self-driving-task-queue`, which the temporal-worker-self-driving fleet polls. Deploy a worker that polls a new queue before you set `AUTORESEARCH_TASK_QUEUE` to it, or the schedule strands its runs.
- `__init__.py`
  The registration surface. `WORKFLOWS` and `ACTIVITIES` are what the worker reads; a workflow that is not in these lists does not exist as far as production is concerned.

## Mental model

```text
daily schedule
   └─ AutoresearchCoordinatorWorkflow
        ├─ activity_load_active_pipelines
        ├─ per pipeline, at most max_concurrency at once, one step at a time:
        │    ├─ AutoresearchInferenceWorkflow   → ../inference/   (champion only)
        │    │    └─ on ChildWorkflowError: activity_fail_lost_inference_runs
        │    ├─ activity_kickoff_training       → ../training/
        │    └─ AutoresearchValidationWorkflow  → ../evaluation/
        └─ after every pipeline above, per completed champion run, under the same bound:
             └─ activity_run_shadow_scoring     → ../inference/

catch-up schedule (08:00, 14:00, 20:00 UTC, catch_up=True)
   └─ AutoresearchCoordinatorWorkflow
        └─ the same tree, for lost pipelines only, without kickoff and validation
```

The bound exists because each scoring activity holds a feature matrix in worker memory and runs batch queries. An unbounded sweep started every pipeline at the same moment, which overloaded ClickHouse and got the shared worker OOM-killed. A pipeline holds its slot through all its steps, so validation never runs next to its own scoring. Discovery lists the due pipelines that did not score yesterday first, so they get the first slots. The ordering and the bound come from recorded history (the activity result and the workflow input), so they are deterministic.
The bounded sweep is behind `workflow.patched("autoresearch-bounded-sweep-2026-10")`. A history without the marker replays the old unbounded sweep in `_run_pipeline()`. Remove that path once no coordinator that started before the patch can still be running.

The coordinator decides _whether_ each pipeline is due; the child workflows do one pipeline's work. Keep that split — per-pipeline logic in the coordinator is what makes a fan-out impossible to reason about.
Validation runs on every daily sweep, because a matured date should not wait for the next scoring day.
Scoring and training kickoff run on a cadence day only, compared by calendar day, and kickoff starts after scoring ends. Validation starts after kickoff.
Discovery pauses a pipeline whose creator has lost access to the team, and skips one outside the flag rollout.
When an inference child ends in an exception, the coordinator fails the runs it left RUNNING, with `failure_kind` `other`, because a lost worker never records an outcome. This is behind `workflow.patched("autoresearch-close-lost-runs-2026-10")`.
Discovery also fails every inference run still RUNNING after `INFERENCE_WORKFLOW_TIMEOUT` (`fail_stale_inference_runs()` in `../inference/failures.py`). This is the backstop for a run that the coordinator did not close.
The catch-up sweep lists only the due pipelines whose latest scheduled run of the day failed with a kind a retry can pass (`scheduled_run_can_retry()`). A pipeline with no run for the day is skipped, because the daily sweep may not have reached it yet, and a second start would score it twice. Its inference children use `ALLOW_DUPLICATE_FAILED_ONLY`, so a catch-up starts only after the daily child of the date failed or timed out. It skips training kickoff and validation, because the daily sweep already ran them.
A retry of a scheduled scoring attempt fills the RUNNING row of the attempt before it, so one date keeps one row.
Kickoff applies the Tasks entitlement and usage gates `/train` applies, launches at most one run per UTC day, and holds the pipeline row lock through the launch, as `start_training` does.
Kickoff then follows the research schedule in `../training/schedule.py`, which it derives from the pipeline's training runs and never stores.
In explore, it starts a run (`explore`) until a completed run does not promote its best model, or until `EXPLORE_RUN_LIMIT` research runs have run. Rescue runs do not count.
In maintain, it starts a run (`scheduled`) once `research_interval_days` calendar days have passed since the latest training run of any kind, and reports `not_due` before that. A null interval reports `manual_only`.
Each run takes the pipeline's `iterations_per_run`. Kickoff does not read or spend `iteration_budget_remaining`.
When no run is due and `find_unscorable_champion()` finds that the champion cannot score, kickoff launches a rescue run of `RESCUE_ITERATION_BUDGET` iterations, at most once in each window of `UNSCORABLE_AFTER_FAILED_DAYS` UTC days, and reports `rescue_unscorable`.
Each run records why it started in `kickoff_reason`. The coordinator body never branches on the kickoff result, because that would break replay.

Note that training is launched by an _activity_, not a child workflow, because the actual agent run happens in a Tasks sandbox with its own lifecycle. Autoresearch does not own that workflow; it fires it and the `TaskRun` `post_save` signal (`../training/ingestion.py`) picks the result back up.

## Payload discipline

Temporal activity payloads are capped at roughly 2 MiB, and autoresearch moves genuinely large data — feature matrices, prediction sets, materialized populations.

**Do all heavy work inside a single activity and return only references.** Scoring writes its events and returns counts; validation computes its metrics inside the activity and returns the summary. Never pass a materialized population or a prediction set through a workflow on its way to being persisted — it will work in dev and fail with `PayloadSizeError` the moment a real team runs it.

## Where the rest of the system meets this package

- **Registered by** — `posthog/management/commands/start_temporal_worker.py`, which imports `WORKFLOWS` / `ACTIVITIES` from here.
- **Scheduled by** — `posthog/temporal/schedule.py`, which calls `create_autoresearch_daily_schedule()`.
- **Calls into** — `../inference/scoring.py`, `../evaluation/online_validation.py`, `../training/runner.py`.
- **Result handoff** — training results come back through the `TaskRun` `post_save` signal wired in `../apps.py`, not through this workflow.

## When editing this flow

- **Editing a `@workflow.defn` body breaks in-flight executions.** Adding, removing, or reordering `execute_activity` calls, child-workflow starts, or timers fails replay with a non-determinism error on every running execution.
  Gate new commands behind `workflow.patched("...")`. A new field on an activity's output dataclass does not replace the patch, because old workflow code can receive that field during a rolling deploy. Activity _implementations_ and activity _input_ dataclasses are safe to edit; command sequences are not.
- **Never gate a workflow command on something computed inside the workflow body** — a feature flag, a setting, the clock, a database read. That is itself non-deterministic.
- Keep scoring, validation and training logic out of the activities. It belongs in the package the activity calls, or the management commands will quietly behave differently from production. Only sweep-specific decisions (what is due, who may launch) stay here.
- New workflows and activities must be added to `WORKFLOWS` / `ACTIVITIES` in `__init__.py` or they are never registered — this fails silently, since nothing errors when a workflow simply never runs.
- **If you add or rename a workflow or activity, update this file to match.**
