---
name: versioning-temporal-workflows
description: >
  Use when editing the body of any `@workflow.defn` class that may have in-flight executions —
  adding, removing, or reordering `execute_activity` / `start_child_workflow` / timer calls,
  changing a child workflow id, or restructuring control flow around them. Covers deciding whether
  `workflow.patched()` gating is required, the patch/deprecate/remove lifecycle, and the
  fingerprint guard for long-running workflows (external-data-job, CDC). Trigger terms:
  workflow.patched, NondeterminismError, Temporal versioning, workflow replay, deprecate_patch,
  workflow_fingerprints.
---

# Versioning Temporal workflows

Temporal workflows are replayed: whenever a worker picks up an in-flight execution (after a deploy, a worker restart, or an activity completing days later), it re-runs the workflow function from the top against the recorded event history.
If the code now issues a different command sequence than the history records, replay fails with `NondeterminismError` and the execution wedges in Running — the workflow task retries forever and even cancel requests can't be processed.

This is not hypothetical: on 2026-07-01 two unversioned edits to `ExternalDataJobWorkflow.run` wedged every in-flight external-data-job execution and blocked all scheduled syncs for the affected schemas.
Long-running workflows are guaranteed to have in-flight executions across every deploy — external-data-job activities run with timeouts up to 1 week plus retries.

## Decide: does this change need `workflow.patched()`?

**Needs gating** (changes the command sequence seen on replay):

- Adding, removing, or reordering `workflow.execute_activity` / `start_activity` / `execute_child_workflow` / `start_child_workflow` calls.
- Changing which activity function or child workflow a call targets, or a child workflow's `id`.
- Adding or removing `workflow.sleep` / `asyncio.sleep` (timers) or `continue_as_new`.
- Moving a command in or out of a conditional whose outcome is the same during replay.

**Safe without gating** (not part of the replayed command sequence):

- Changing activity _input payloads_ (adding a dataclass field — but see the worker-rollout caveat below), timeouts, retry policies, or heartbeat settings.
- Log lines, comments, metrics, renames of local variables.
- Changes inside _activities_ — activities are not replayed, only their recorded results are.
- A brand-new workflow definition (no history exists yet).

Worker-rollout caveat: payload shape changes are replay-safe but not deploy-atomic — old workers may still receive the new payload mid-rollout (see the tuple-vs-dataclass safety net in `external_data_job.py`).

## How to gate a change

```python
if workflow.patched("my-change-id"):
    # new command sequence
    await workflow.execute_activity(new_activity, ...)
else:
    # exact command sequence the old code issued
    await workflow.execute_activity(old_activity, ...)
```

- Executions started _before_ the deploy replay down the `else` branch (their history has no patch marker); new executions record the marker and take the new path.
- The patch id must be unique within the workflow; use a short kebab-case description of the change.
- Purely _additive_ commands still need the gate: `if workflow.patched("add-repartition"): await workflow.execute_activity(maybe_repartition_table_activity, ...)` — with no `else`.

Lifecycle (upstream docs: [Temporal Python versioning](https://docs.temporal.io/develop/python/versioning)):

1. Ship the `workflow.patched("id")` gate.
2. Once no execution started before step 1 can still be running or replaying (for external-data-job: activity timeout × retries — think weeks, not days), optionally replace the conditional with `workflow.deprecate_patch("id")` + only the new code.
3. Once no execution from step 2 remains, delete the marker entirely.

Steps 2–3 are cleanup; skipping them is safe, just untidy. Removing a `patched()` call too early is itself a replay-breaking change.

## The fingerprint guard

Long-running workflow files are registered in `posthog/temporal/common/workflow_fingerprints.py` (`REGISTERED_WORKFLOW_FILES`).
A test (`posthog/temporal/common/test_workflow_fingerprints.py`) extracts each `@workflow.defn` class's source-ordered command sequence and compares it against the committed baseline `workflow_fingerprints.json`.
Any sequence-affecting edit fails the test until the baseline is regenerated:

```sh
python posthog/temporal/common/workflow_fingerprints.py
```

Only regenerate after the change is gated with `workflow.patched()` (or the workflow verifiably has no in-flight executions).
The baseline diff in your PR shows reviewers exactly what changed in the command sequence.

To enroll another long-running workflow file, add its repo-relative path to `REGISTERED_WORKFLOW_FILES` and regenerate.
Enroll any workflow whose executions routinely span deploys (currently: external-data-job and CDC; batch exports is a good candidate — coordinate with the owning team before enrolling files you don't own).

## If production is already wedged

An unversioned change already deployed shows up as workflows stuck in Running with `NondeterminismError` in the workflow task failure (Temporal UI), unprocessable cancels, and schedules not producing new runs (buffered behind the stuck one).

- Fastest fix: make replay succeed again — revert the change, or re-ship it behind `workflow.patched()` with the old sequence in the `else` branch. Stuck executions recover on the next workflow task retry; no data is lost.
- If the old code path is truly gone: `temporal workflow terminate` the stuck executions (they cannot be cancelled) and let the schedule start fresh runs. Terminated syncs restart from their last committed state.
