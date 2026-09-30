# Online evaluation execution usage

`llma evaluation run recorded` tracks evaluation results accepted by capture, including skipped results.
It covers Hog and LLM judges on generation, trace, and session targets, plus generation sentiment.
The event uses `org-<organization_id>` as its distinct ID and attaches organization and project groups.
Use organization groups to measure adoption by output type.

## Event properties

- `evaluation_id`, `team_id`, and `run_id` identify the evaluation, project, and execution.
- `output_type`, `evaluation_type`, and `target` distinguish the result type, method, and evaluation target.
- `selection_mode` is `single` or `multiple` for categorical results only.
- `status` is `completed` or `skipped`.
- `applicable` distinguishes a valid result from N/A or a skipped run.
- `trigger` is `live` or `backfill`.

The event contains no scores, category keys or labels, prompts, outputs, reasoning, or source event identifiers.

## Counting usage

Count distinct `run_id` values to avoid retry inflation.
The run ID and event UUID derive from the workflow ID, and the timestamp is the evaluation start time, including for backfills.
Use `trigger=live` for current traffic and `trigger=backfill` for historical jobs.
Live includes explicit re-runs through the run endpoint; previews do not emit this event.

For active organizations, require `status=completed` and `applicable=true`.
Completed results count regardless of whether they pass the customer's rule.
An empty categorical result is applicable; an intentional N/A result has `status=completed` and `applicable=false`.
Keep internal test organizations separate using organization filters, since employee person filters do not cover background events.

Capture acceptance does not confirm ingestion.
Billing-blocked results and failures before capture acceptance do not emit this event; use workflow/error metrics for those failures.
The older `llm analytics evaluation executed` event excludes generation Hog executions and skipped runs.
It remains unchanged for existing consumers; do not combine the two events for usage totals.
Coverage starts when the worker change deploys.

Creation already exposes `output_type` on `llma evaluation created`, so existing creation charts can use that breakdown.
