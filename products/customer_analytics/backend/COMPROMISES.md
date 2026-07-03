# Customer analytics — v1 compromises

Shortcuts taken to ship the first version. Revisit when they bite.

## Custom property view sync

- **Celery, not Temporal.** The sync runs in a Celery task, not a dedicated Temporal workflow. No
  durable retries and no run-level UI inspection — failures surface via `last_sync_error` on the
  source + error tracking. Move to Temporal if we need durable retries, long-running syncs, or
  per-run inspection.
- **No retries.** A failed run is not retried; it records the failure (advancing the auto-disable
  streak) and waits for the next materialization. Only transient write conflicts retry, in-logic.
- **Direct dispatch by task name, not a signal.** Core (`succeed_materialization_activity`) enqueues
  this product's sync task by name via `send_task`. A generic core signal the product subscribes to
  would keep core ignorant of the consumer, but for a single consumer that isn't worth the wiring (a
  signal definition + a receiver + an app-ready hook). By-name dispatch also keeps the product and
  HogQL out of the data-modeling worker's process, since core imports nothing from here. Trade-off:
  core hardcodes this consumer's task name. If a second consumer ever needs the materialization event,
  switch to a core-owned signal (inversion of control) rather than adding another direct dispatch.
- **No save-time column validation.** Creating/updating a source does not check that `source_column`
  / `key_column` exist in the view's schema. A bad column surfaces as a per-source sync error (and
  advances the auto-disable streak) on the next run, not as a 400 on save. Validate against the saved
  query's `columns` at write time if the delayed feedback bites.
- **Initial sync is best-effort.** Saving an enabled source enqueues a sync on commit so values
  populate without waiting for the next materialization. If the broker is down the save still
  succeeds and the enqueue is dropped (logged to error tracking) — the next materialization recovers.
- **v2 materialization only.** v1 `run_workflow.py` is frozen and does not dispatch the sync; v1
  teams get it after migrating to v2.
