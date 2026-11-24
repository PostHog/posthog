---
name: replaying-failed-cdp-runs
description: >
  Sends destination and workflow runs that failed during an incident again, across teams, with the staff
  "Replay failed CDP runs" admin console tool. Use after a CDP incident (expired integration tokens, an outage
  at a provider, a broken deploy) when failed destination or workflow runs should be sent again, when someone
  asks for a link to the replay tool with filters, or when checking whether a replay worked.
  Covers building the prefilled link, choosing the window and error filter, which runs not to replay, and
  checking whether the replayed runs were delivered.
---

# Replaying failed CDP runs

The tool lives at `/admin/console/tools/replay-failed-runs/` on each region (`https://us.posthog.com`, `https://eu.posthog.com`).
Staff open it; an agent builds the link and checks the result.
The code is in `products/cdp/backend/console.py` and `products/cdp/backend/services/invocation_replay.py`.

## Build the link

Every filter is a query parameter, so a link opens the preview with the filters filled in.
Nothing is sent until a person confirms the count on the send page.

| Parameter                                                                          | Value                                                                                   |
| ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `window_start`, `window_end`                                                       | UTC, `2026-11-17 12:30:00`. Matches the time of each run's latest attempt.              |
| `error_message_contains`                                                           | Text from the incident's error, ignoring case, like `expired` or `401`                  |
| `error_kinds`                                                                      | Comma-separated, like `http_4xx`. Combined with the text using AND, so it only narrows. |
| `template_ids`, `exclude_template_ids`, `team_ids`                                 | Comma-separated                                                                         |
| `include_workflows`                                                                | `on` to also continue workflow runs from their failed step                              |
| `latest_per_person_template_ids`                                                   | Templates that sync a person's current state. Default `template-hubspot`.               |
| `require_success_since_window`, `skip_already_rerun`, `skip_failing_before_window` | Safety checks, on by default                                                            |
| `edit=1`                                                                           | Opens the form instead of the preview, so a person checks the filters first             |

A parameter left out keeps its default. To turn a check off, pass `false`; `0` does not work, because Django reads any other text as on.
Write the window and the error text from the data, not from the alert: query `hog_invocation_results` for the failed runs first (below) and set the window around their latest attempts.

## Choose what to replay

- A run's latest attempt sets its time. Runs the tool already replayed have their latest attempt at the replay time, so a second replay of them needs a window around that time and `skip_already_rerun=false`.
- Leave `skip_failing_before_window` on, unless the error also happens outside incidents, like a provider rate limit.
  Then it skips the very runs you want.
- Leave out sends that hurt when late, like push notifications and reminder emails, and workflows unless the person who asked wants them continued.
  Say what you left out and why.
- A contact sync whose fields come from the event (the function's inputs mention `event.`) writes the old event's values.
  Keep it in `latest_per_person_template_ids`, so a newer successful sync is never overwritten.

## Check the outcome

The status page of a sent replay has a "Delivery of the replayed runs" table.
It shows the latest attempt of every run the replay queued: delivered, failed again, sending, or no new attempt yet, with the most common errors of the runs that failed again.
It refreshes until no run is sending or waiting, so send the person the status page link (`?plan=<fingerprint>`) to check the result.

"Requests sent" and "Requests failed" above it count the rerun jobs the tool queued, not whether the destination accepted the runs.
A run with no new attempt yet is still queued, or the rerun found it no longer failed and skipped it.
The table needs the replay record, which expires after 7 days, and replays sent before the table existed have none.
For those, query `hog_invocation_results` yourself. List the failed runs a preview covers before anyone sends, because the failed attempts can drop out once a rerun lands:

```sql
SELECT DISTINCT invocation_id
FROM hog_invocation_results
WHERE function_kind = 'hog_function' AND status = 'failed'
  AND scheduled_at >= '<window_start>' AND scheduled_at < '<window_end>'
  AND positionCaseInsensitive(error_message, '<error text>') > 0
```

After the status shows done, count the latest status of those IDs:

```sql
SELECT final_status, count() AS runs, uniq(team_id) AS teams
FROM (
    SELECT team_id, invocation_id, argMax(status, version) AS final_status
    FROM hog_invocation_results
    WHERE function_kind = 'hog_function' AND invocation_id IN (<saved ids>)
    GROUP BY team_id, invocation_id
)
GROUP BY final_status
```

Then group the runs that still failed by their latest `error_message`.
Rate limits from the replay's own burst can be sent again; errors in the customer's own data cannot.
Run both with `/querying-production-databases`.

A preview with the original window is not an outcome check: a rerun's latest attempt falls after the window, so the preview leaves it out whether it succeeded or failed.
