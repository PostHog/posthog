# Temporal workflows

The scheduled half of autoresearch. Three workflows and five activities, registered on the `autoresearch-task-queue` by `start_temporal_worker`, which imports `WORKFLOWS` and `ACTIVITIES` from `__init__.py`.

Nothing here implements product logic. Every activity is a thin call into `../inference/`, `../evaluation/`, or `../training/` — the same functions the management commands and the API reach. That is deliberate: the scheduled path must not be able to drift from the headless one.

## What lives here

- `workflows.py`
  - `AutoresearchCoordinatorWorkflow` (`autoresearch-coordinator`) — the daily tick. Loads active pipelines (`activity_load_active_pipelines`) and fans out inference, validation, and training kickoff per pipeline.
  - `AutoresearchInferenceWorkflow` (`autoresearch-inference`) — `activity_load_champion` then `activity_run_inference` for one pipeline.
  - `AutoresearchValidationWorkflow` (`autoresearch-validation`) — `activity_run_validation` for one pipeline.
  - `activity_kickoff_training` — launches a training run for a pipeline that is due.

  Each workflow has a typed input/result dataclass pair (`InferenceWorkflowInput` / `InferenceWorkflowResult`, and so on). Activities are named with a `autoresearch-<workflow>.<activity>` convention.

- `schedule.py`
  `create_autoresearch_daily_schedule()` registers schedule `autoresearch-daily-coordinator` driving workflow id `autoresearch-coordinator`.
  Overlap policy is **SKIP** — a tick that is still running causes the next one to be dropped rather than queued, so a slow day cannot pile up a backlog of duplicate scoring runs.
- `__init__.py`
  The registration surface. `WORKFLOWS` and `ACTIVITIES` are what the worker reads; a workflow that is not in these lists does not exist as far as production is concerned.

## Mental model

```text
daily schedule
   └─ AutoresearchCoordinatorWorkflow
        ├─ activity_load_active_pipelines
        └─ per pipeline:
             ├─ AutoresearchInferenceWorkflow   → ../inference/
             ├─ AutoresearchValidationWorkflow  → ../evaluation/
             └─ activity_kickoff_training       → ../training/
```

The coordinator decides _whether_ each pipeline is due; the child workflows do one pipeline's work. Keep that split — per-pipeline logic in the coordinator is what makes a fan-out impossible to reason about.

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
  Gate new commands behind `workflow.patched("...")`, or on a new field of an existing activity's output dataclass that defaults to the skip value. Activity _implementations_ and activity _input_ dataclasses are safe to edit; command sequences are not.
- **Never gate a workflow command on something computed inside the workflow body** — a feature flag, a setting, the clock, a database read. That is itself non-deterministic.
- Keep activities thin. If you are writing product logic here, it belongs in the package the activity calls, or the management commands will quietly behave differently from production.
- New workflows and activities must be added to `WORKFLOWS` / `ACTIVITIES` in `__init__.py` or they are never registered — this fails silently, since nothing errors when a workflow simply never runs.
- **If you add or rename a workflow or activity, update this file to match.**
