# Online evaluation usage

Use organization groups to measure adoption across numeric and categorical evaluations.
Creation events use a user distinct ID; background events use `org-<organization_id>`.
Both attach the same organization and project groups.
Match `evaluation_id` as well as the organization when measuring creation to first result.

| Event                                    | Meaning                                                                                                                                                               |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `llma evaluation created`                | A saved evaluation, including its output type, method, target, N/A setting, and passing-rule presence.                                                                |
| `llma evaluation updated`                | A configuration change with the current output metadata.                                                                                                              |
| `llma evaluation hog code tested`        | A preview, including the output metadata and `trigger=preview`. Preview runs do not emit the recorded-run event.                                                      |
| `llma evaluation run recorded`           | An evaluation result accepted by capture, including a skipped result. Covers Hog and LLM judges on generation, trace, and session targets, plus generation sentiment. |
| `llma evaluation automatically disabled` | The first transition from enabled to disabled after a terminal configuration or provider error, with its status-reason code.                                          |
| `llma evaluation report generated`       | A stored report, including its generation status. This does not confirm Slack or email delivery.                                                                      |

Categorical metadata includes `selection_mode` and `category_count`.
An empty categorical passing rule still counts as a configured rule.
New usage events contain no scores, bounds, thresholds, category keys or labels, prompts, outputs, reasoning, or source event identifiers.

## Run counting

Filter the recorded-run event by `output_type`, `evaluation_type`, and `target`.
Use `trigger=live` for current traffic and `trigger=backfill` for historical jobs.
Live includes explicit re-runs through the run endpoint; the separate `llma evaluation run triggered` event identifies those manual requests.
Count distinct `run_id` values to avoid retry inflation.
The run ID and event UUID derive from the workflow ID, and the timestamp is the evaluation start time, including for backfills.

`status=completed` means execution produced a result, regardless of whether the result passed the customer's rule.
Require `applicable=true` when measuring activation through a valid score or category result.
`status=skipped` carries the internal skip-reason code; it is separate from an intentional N/A result (`status=completed`, `applicable=false`).
An empty categorical result is applicable.

The event records capture acceptance, not confirmed ingestion.
Billing-blocked results and failures before capture acceptance do not emit it.
Use workflow/error metrics for those failures; a skip-rate chart over recorded runs is not a total workflow failure rate.
Automatically disabled events count evaluations, not failed runs.
Report generation failures that do not store a report remain workflow errors; stored fallback reports expose `generation_status`.

The older `llm analytics evaluation executed` event remains unchanged for existing consumers.
It excludes generation Hog executions and skipped runs, so do not combine it with the recorded-run event for adoption or reliability totals.
The new coverage starts when the worker change deploys; older time ranges are incomplete.

## Rollout dashboard

- Exposure: organizations with `$feature_flag_called` returning true for the numeric or categorical creation flag.
  A flag check is an exposure proxy, not proof of editor interaction.
- Creation: distinct evaluations and organizations, split by `output_type`.
- Activation: saved evaluations with an applicable completed live run within 24 hours of creation.
  Exclude creations less than 24 hours old from the denominator and use the new tracking deployment as the cohort start.
- Continued use: organizations with applicable completed live runs this week, and return usage the following week.
- Reliability: recorded skips by reason, automatic disabling by reason, and stored reports by generation status, alongside workflow error metrics.

Keep pilot and internal test organizations in separate cohorts.
Person-based employee filters do not cover background events whose identity is an organization.
Keep numeric and categorical breakdowns separate when deciding whether to expand rollout.
