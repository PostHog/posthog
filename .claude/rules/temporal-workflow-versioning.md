---
paths:
  - 'posthog/temporal/**'
  - 'products/*/backend/temporal/**'
---

**Editing a `@workflow.defn` body (adding/removing/reordering `execute_activity`, child-workflow
starts, or timers) breaks in-flight executions with "Non Deterministic Error"** — on deploy every
running execution replays its recorded history against the new code, and any new unconditional
command at a point an execution already passed fails the replay. Activity implementations and
activity _input_ dataclasses are safe to edit; workflow command sequences are not.

When adding a new activity or child-workflow start to an existing workflow, gate it one of two ways:

1. `if workflow.patched("my-change-2026-07"): ...` — the default. Old histories skip the block,
   new executions record a marker and run it. Precedent: `posthog/temporal/ai_observability/run_evaluation.py`.
   Once no pre-patch executions remain (days, for short-lived workflows), optionally swap to
   `workflow.deprecate_patch(...)` + unconditional code.
2. Gate on a **new field of an existing activity's output dataclass that defaults to the skip
   value** (e.g. `enrichment_needed: bool = False` in `create_job_model.py`) — old histories decode
   the missing field to the default, so the new command never fires during replay. Only valid when
   the decision comes from recorded history and skipping is acceptable for in-flight runs.

Never gate workflow commands on values computed inside the workflow body (feature flags, settings,
clock, DB reads) — that is itself non-deterministic. Removing/reordering existing commands needs
`workflow.patched()` with the old path kept in the `else` branch.
