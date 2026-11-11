---
name: authoring-insight-alerts
description: >
  Author insight alerts that notify when a trends, SQL, or funnel insight crosses a bound, changes sharply,
  or looks anomalous. Use when the user asks to alert on a metric or insight, get notified when a number
  drops or spikes, set up anomaly detection, or use the AI anomaly detector (the llm detector type).
  Covers choosing between threshold, relative change, statistical detector, and AI detector, previewing
  with alert-simulate before saving, the AI detector's credit cost and limits, the exact create payload,
  and delivery by email or Slack.
---

# Authoring insight alerts

An insight alert checks one saved insight on a schedule and notifies people when the latest value breaks a rule.
The job is to pick the rule that matches what the user means by "something is wrong",
preview it against real history,
and ship it with a cadence and a destination the user agreed to.

## When to use this skill

- The user asks to alert on a saved insight, a metric, or a SQL query result.
- The user wants anomaly detection on a metric, or asks for the AI detector.
- The user asks which kind of alert fits a metric.

## When not to use this skill

- Alerts on log lines: use `authoring-log-alerts`.
- Alerts on exceptions or error tracking issues: use `authoring-error-tracking-alerts`.
- Explaining why an existing alert fired: read its checks with `posthog:alert-get`, then investigate the metric.

## Tools

| Tool                                     | Job                                                             |
| ---------------------------------------- | --------------------------------------------------------------- |
| `posthog:insight-get`                    | Read the insight's query kind, interval, series, and breakdown. |
| `posthog:alerts-list`                    | Find alerts that already watch the insight (`insight_id`).      |
| `posthog:alert-simulate`                 | Preview a detector on the insight's history without saving.     |
| `posthog:alert-create`                   | Save the alert.                                                 |
| `posthog:alert-update`                   | Change, disable, or snooze an alert.                            |
| `posthog:alert-get`                      | Read an alert's config and recent checks.                       |
| `posthog:integrations-channels-retrieve` | List connected Slack workspaces and channels.                   |
| `posthog:alert-destinations-create`      | Post the alert to a Slack channel as well as email.             |
| `posthog:user-get`                       | Look up a user ID for `subscribed_users`.                       |

## Workflow

### 1. Read the insight and the alerts already on it

Call `posthog:insight-get` and note:

- The query kind: `TrendsQuery`, `HogQLQuery` (SQL), or `FunnelsQuery`. It decides the `config` type.
- The interval (hour, day, week) and how many series or formula results it returns.
- Whether it has a breakdown, and for trends whether it is a time series (a line or bar chart over time, not a single number or a pie).

Call `posthog:alerts-list` with `insight_id`.
If an alert already watches the same series, offer to change it with `posthog:alert-update` instead of adding a second one.
Each plan limits the number of alerts, so a duplicate can block an alert the user needs later.

If no saved insight measures what the user wants, create the insight first, then come back here.

### 2. Pick the alert type

Ask what "wrong" means for this metric, then map the answer:

| The user says                                                        | Alert type                   | Shape                                                                    |
| -------------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------ |
| "Tell me if it goes above 500" or "below 10"                         | Threshold                    | `condition: absolute_value`, absolute `lower` or `upper` bound.          |
| "Tell me if it drops 20% from the previous period"                   | Relative change              | `condition: relative_decrease` or `relative_increase`, percentage bound. |
| "Tell me if it looks unusual" on a noisy or seasonal metric          | Statistical detector         | `detector_config` with `zscore`, `mad`, or `iqr`, or an `ensemble`.      |
| What counts as unusual is easier to describe in words than a number  | AI detector                  | `detector_config: {"type": "llm", "instructions": "..."}`.               |
| "Tell me if it stops", for example no signups or a missing heartbeat | Threshold with a lower bound | `absolute_value` with `lower: 1`.                                        |

Prefer the simplest type that matches.
A fixed bound is easy to read in a notification and costs nothing to run.
Use a detector when the user cannot name a number, or when the metric's normal level moves too much for a fixed bound.

Detectors work on trends and SQL insights, not funnels.
On a trends insight they need a time series.
See [references/payloads.md](./references/payloads.md) for the exact payload for each type and insight kind.

### 3. Pick the cadence

`calculation_interval` is one of `hourly`, `daily`, `weekly`, `monthly`, `every_15_minutes`, or `real_time`.
If the user did not say how often to check, ask.
When they want "as fast as possible", propose `hourly`.

- `every_15_minutes` needs a Boost, Scale, or Enterprise add-on, and `real_time` needs a Scale or Enterprise plan.
  A create refused on `calculation_interval` means the plan does not include that cadence.
  Tell the user and offer `hourly`. Do not try other fast cadences on your own.
- A cadence faster than the insight's interval checks the same completed bucket until the next one closes.
  For an hourly check of a daily insight, set `check_ongoing_interval: true` with an upper bound so the check reads the day in progress.
- The AI detector cannot run on `real_time`.
  Prefer `daily` or `hourly` for it, because every check is charged.

### 4. Preview before saving

Call `posthog:alert-simulate` with the insight and the `detector_config` you plan to save.
Always send `detector_config.type`: a config without a type is read as a z-score detector.

- For a statistical detector, pass `date_from` (for example `-30d`) and, on trends, `series_index`.
  Read `triggered_dates`. A good draft flags the incidents the user remembers and little else.
  If it flags many points, raise `threshold` (sensitivity, 0 to 1) or `window`, or switch to `mad`, which outliers move less.
  If it flags nothing in a history that had incidents, lower `threshold`.
- For a fixed bound, simulate a `threshold` detector with the same `lower_bound` or `upper_bound` to see which past points would have breached.
- For a SQL insight, pass the `config` (`HogQLAlertConfig`) you will save, so the preview reads the same column and rows.
- For the AI detector, simulate makes one live check of the latest point. It does not scan the history.
  It returns `rationale` and `kind`, and `triggered_indices` holds the latest point when it fires.
  It uses the organization's AI credits and needs the `alert:write` scope, so run it once or twice, not in a loop.
  For a saved alert, pass `alert` with its ID so the model also sees the points that alert's earlier checks fired on.

Stop after three simulations per alert.
If none gives a reasonable result, tell the user what you saw and suggest a different alert type.

### 5. Create the alert

Show the user the alert you are about to create: insight, rule, cadence, and recipients.
For the AI detector, also state the cost from [Cost and limits](#cost-and-limits).
Then call `posthog:alert-create`.

Every create needs `insight`, `subscribed_users`, `condition`, `threshold`, and `config`, detector alerts included.
Most failed creates leave one of these out or put a field under the wrong key.
Copy the shape from [references/payloads.md](./references/payloads.md), which also lists the common refusals and how to fix each one.
Read a refusal before retrying, and do not resend the same payload.

Name alerts after what they watch, for example `Signups below 10 per day`.

### 6. Deliver

- `subscribed_users` get email. Add at least the user who asked, unless they say otherwise.
- For Slack, find the workspace and channel with `posthog:integrations-channels-retrieve`, confirm the channel with the user, then call `posthog:alert-destinations-create` with the alert ID.
  An alert can have up to 5 destinations.
- For a webhook or Discord, follow the recipe in the `posthog:cdp-functions-create` description.

Confirm with the user before posting a new alert to a busy shared channel.

## The AI detector

The AI detector (`detector_config.type: "llm"`) asks a model one question on every check: is the latest point unusual, given its history?
The answer is the fire decision.
There is no score and no sensitivity to tune.

### Availability

The detector is available only where the `alerts-llm-detector` rollout is on for the organization and AI data processing is approved in organization settings.
If create or simulate is refused for either reason, tell the user what to change and offer a statistical detector.

### Cost and limits

Tell the user these before you create an AI detector alert:

- Every scheduled check and every simulation is a model call charged to the organization's AI credits.
  A daily alert makes about 30 calls a month, and an hourly alert about 720.
- Each project has a cap on enabled AI detector alerts.
  The refusal names the current count and the cap. Disabling an AI alert frees a slot.
- It cannot run on `real_time`, cannot watch a breakdown insight, and cannot be part of an ensemble.
  It takes no `preprocessing`, `threshold`, or `window` fields.
- When the organization runs out of AI credits, checks record an error and the alert stays on.

### Writing instructions

`instructions` is optional plain text, up to 2000 characters.
Without it, the model judges the shape on its own.
Good instructions say:

- Which direction matters: "A drop is bad. A rise is fine."
- Known cycles: "Weekends are about 40% lower than weekdays. The first Monday of the month spikes from billing runs."
- What to ignore: "Ignore single-hour dips under 10%."
- Known changes in the history: "A tracking fix on 2026-10-01 halved the count, so the earlier level is not the baseline."

Do not put secrets or personal data in instructions. The model reads them on every check.

### Reading AI detector results

AI checks have no anomaly scores.
`posthog:alert-get` returns each check's `triggered_metadata`, which carries the model's `rationale` and a `kind`:
`spike`, `drop`, `flatline`, `trend_break`, `level_shift`, `pattern_change`, or `none`.
Later checks see the points that earlier checks fired on, with their rationale, so instructions can refer to earlier alerts.

## Output

Report, for each alert:

- Name, insight, rule (bounds, detector, or AI instructions), and cadence.
- What the preview showed: flagged dates for a statistical detector, or the verdict and rationale for the AI detector.
- Recipients and destinations.
- For the AI detector, the call estimate you gave the user.

For each alert you did not create, say why: a plan limit, a refused cadence, or no rule that fit the history.

## Related skills

- `authoring-log-alerts`: alerts on log volume and errors.
- `authoring-error-tracking-alerts`: alerts on new, reopened, or spiking exceptions.
- `investigate-metric`: explain why an insight's metric moved after an alert fires.
