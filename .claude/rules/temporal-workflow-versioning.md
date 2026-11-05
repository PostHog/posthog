---
paths:
  - 'posthog/temporal/**'
  - 'products/*/backend/temporal/**'
---

**Changing which commands a `@workflow.defn` body emits breaks in-flight executions with "Non Deterministic Error".**
Commands are `execute_activity` calls, child-workflow starts, timers (`workflow.sleep`) and patch markers.
On deploy, every running execution replays its recorded history against the new code.
The replay fails when the new code emits a command that the history does not have.
It also fails when the new code skips a command that the history has.
Temporal retries the failed workflow task forever, so the execution hangs.
Activity implementations and activity _input_ dataclasses are safe to edit; workflow command sequences are not.

Gate every change to the command sequence with `if workflow.patched("my-change-2026-07"): ...`.
Old histories have no marker, so they keep the old commands.
New executions record the marker and run the new code.
Precedent: `posthog/temporal/ai_observability/run_evaluation.py`.
Removing or reordering existing commands keeps the old path in the `else` branch.
Once no pre-patch executions remain (days, for short-lived workflows), you can swap to `workflow.deprecate_patch(...)` + unconditional code.

**New data does not replace the patch.**
A condition on data that old code ignores changes the command sequence just as new code does.
This covers a new field on an activity's output dataclass that defaults to the old behavior.
It also covers a new key in a dict that an activity reads from the database, such as run state that the same change starts to write.
In a rolling deploy, old workflow code can receive the new data.
A new pod on the same task queue can return it.
A new web pod can also write it before the workers roll.
Old workflow code ignores the data and records the old commands.
The new code then replays that history and acts on the data, so every replay of that execution fails.
Put the patch in front of the data check (`if workflow.patched("x") and result.skip_it: ...`), so a history without the marker keeps the old commands.

**A new condition in front of an existing `workflow.patched(...)` call needs its own patch.**
When the condition skips the call, Temporal records no marker.
Histories that recorded the marker then fail to replay.

Where the decision can live in an activity, put it there instead.
The activity returns early, the workflow keeps the same commands and no patch is needed.

Never gate workflow commands on values computed inside the workflow body (feature flags, settings, clock, DB reads).
That is itself non-deterministic.
