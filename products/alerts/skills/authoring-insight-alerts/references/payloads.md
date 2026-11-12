# Insight alert payloads

Exact shapes for `posthog:alert-create` and `posthog:alert-simulate`.
Every example uses invented IDs.

## Contents

- [Fields every create needs](#fields-every-create-needs)
- [Threshold alerts](#threshold-alerts)
  - [Fixed bound on a trends insight](#fixed-bound-on-a-trends-insight)
  - [Silence check: the metric stops](#silence-check-the-metric-stops)
  - [Relative change](#relative-change)
- [Detector alerts](#detector-alerts)
  - [Statistical detector parameters](#statistical-detector-parameters)
  - [Ensemble](#ensemble)
  - [AI detector](#ai-detector)
- [Config by insight kind](#config-by-insight-kind)
  - [SQL insight (`HogQLQuery`)](#sql-insight-hogqlquery)
  - [Funnel insight (`FunnelsQuery`)](#funnel-insight-funnelsquery)
- [`alert-simulate`](#alert-simulate)
- [Common refusals](#common-refusals)

## Fields every create needs

| Field                  | Shape                                                                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `insight`              | The insight's numeric ID.                                                                                                            |
| `subscribed_users`     | A list of user IDs (integers) who get email. Use `[]` only if the user asks for no email.                                            |
| `condition`            | `{"type": "absolute_value"}`, `{"type": "relative_increase"}`, or `{"type": "relative_decrease"}`. Required for detector alerts too. |
| `threshold`            | `{"configuration": {"type": "absolute" or "percentage", "bounds": {"lower": ..., "upper": ...}}}`. Required for detector alerts too. |
| `config`               | The config for the insight kind: `TrendsAlertConfig`, `HogQLAlertConfig`, or `FunnelsAlertConfig`.                                   |
| `calculation_interval` | `hourly`, `daily`, `weekly`, `monthly`, `every_15_minutes`, or `real_time`. Defaults to `daily`.                                     |

Optional: `name`, `enabled`, `detector_config`, `skip_weekend`, `schedule_start_time` (local `HH:MM`), `evaluation_delay_intervals`.

Send these fields at the top level of the tool input.
Do not wrap them in an `alert` object.

## Threshold alerts

### Fixed bound on a trends insight

```json
{
  "insight": 12345,
  "name": "Checkout errors above 50 per hour",
  "subscribed_users": [42],
  "condition": { "type": "absolute_value" },
  "threshold": { "configuration": { "type": "absolute", "bounds": { "upper": 50 } } },
  "config": { "type": "TrendsAlertConfig", "series_index": 0 },
  "calculation_interval": "hourly"
}
```

- `series_index` is zero-based.
  With formulas, it indexes the formula results, not the raw series.
- At least one of `lower` or `upper` is required when there is no `detector_config`.
- `lower` must be less than `upper` when both are set.

### Silence check: the metric stops

```json
{
  "condition": { "type": "absolute_value" },
  "threshold": { "configuration": { "type": "absolute", "bounds": { "lower": 1 } } },
  "config": { "type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": false }
}
```

Keep `check_ongoing_interval` off with a lower bound.
An ongoing bucket is still filling, so it is always low early in the period, and the server refuses the combination.

### Relative change

```json
{
  "condition": { "type": "relative_decrease" },
  "threshold": { "configuration": { "type": "percentage", "bounds": { "upper": 0.2 } } },
  "config": { "type": "TrendsAlertConfig", "series_index": 0 }
}
```

- A percentage bound is a fraction: `0.2` means 20%.
- The change is measured against the previous interval of the insight.
- `relative_decrease` with `upper: 0.2` fires when the value falls by more than 20%.
- `absolute_value` needs an `absolute` threshold type.
  `relative_*` can use either type: `absolute` compares the raw difference.
- Relative conditions need a time-series trends insight, or a historical-trend funnel.

## Detector alerts

A detector alert still sends `condition` and `threshold`.
The bounds are not used, so send `{"configuration": {"type": "absolute"}}`.

```json
{
  "insight": 12345,
  "name": "Daily signups look unusual",
  "subscribed_users": [42],
  "condition": { "type": "absolute_value" },
  "threshold": { "configuration": { "type": "absolute" } },
  "config": { "type": "TrendsAlertConfig", "series_index": 0 },
  "calculation_interval": "daily",
  "detector_config": { "type": "zscore", "threshold": 0.95, "window": 30 }
}
```

### Statistical detector parameters

Always send `type`.
Each detector accepts only its own fields, and an unknown field makes the whole config invalid.

| Type        | Fields and ranges                                                                       |
| ----------- | --------------------------------------------------------------------------------------- |
| `zscore`    | `threshold` 0 to 1 (default 0.9), `window` 5 to 1000 (default 30), `preprocessing`.     |
| `mad`       | `threshold` 0 to 1 (default 0.9), `window` 5 to 1000 (default 30), `preprocessing`.     |
| `iqr`       | `multiplier` 0.5 to 10 (default 1.5), `window` 5 to 1000 (default 30), `preprocessing`. |
| `threshold` | `lower_bound`, `upper_bound`, `preprocessing`.                                          |

`preprocessing` is `{"diffs_n": 0 or 1, "smooth_n": 0 to 30, "lags_n": 0 to 10}`, and every key is optional.
`diffs_n: 1` scores the change between points instead of the level, which suits a metric with a trend.

The other types (`copod`, `ecod`, `hbos`, `isolation_forest`, `knn`, `lof`, `ocsvm`, `pca`) are multivariate methods.
Start with `zscore` or `mad` and move to these only when the user asks.

### Ensemble

```json
{
  "type": "ensemble",
  "operator": "and",
  "detectors": [
    { "type": "zscore", "threshold": 0.95, "window": 30 },
    { "type": "mad", "threshold": 0.95, "window": 30 }
  ]
}
```

- `operator` is lowercase: `"and"` or `"or"`.
  `"and"` fires only when every member flags the point, which cuts noise.
  `"or"` fires when any member does.
- An ensemble needs at least two members, and cannot include `llm`.

### AI detector

```json
{
  "type": "llm",
  "instructions": "A drop is bad and a rise is fine. Weekends run about 40% lower than weekdays."
}
```

- `type` and `instructions` are the only fields.
  `threshold`, `window`, and `preprocessing` are refused.
- Not on `real_time`, not on breakdown insights, and not in an ensemble.

## Config by insight kind

### SQL insight (`HogQLQuery`)

```json
{ "type": "HogQLAlertConfig", "evaluation": "last_row", "column": "errors", "label_column": "day" }
```

- `evaluation` is required.
  `last_row` reads the last row of a query ordered oldest to newest.
  `first_row` reads the first row of a query ordered newest to oldest, which pairs well with a `LIMIT`.
  `any_row` checks every row and fires if any breaches. It works only with `absolute_value` and no detector.
- `column` defaults to the single numeric column. Set it when the query returns more than one.
- `label_column` names the row in notifications. Do not pick a column with personal data.

### Funnel insight (`FunnelsQuery`)

```json
{ "type": "FunnelsAlertConfig", "funnel_step": null, "metric": "conversion_from_start" }
```

- `funnel_step` is zero-based. `null` watches overall conversion to the last step.
- `metric` is `conversion_from_start` or `conversion_from_previous`.
- Conversion is a percentage from 0 to 100, so `lower: 25` fires below 25%.
  This differs from a relative change bound, which is a fraction.
- A steps funnel supports only `absolute_value`.
  A historical-trend funnel also supports relative conditions.
- Funnels do not support detectors.

## `alert-simulate`

```json
{
  "insight": "aBcD1234",
  "detector_config": { "type": "mad", "threshold": 0.9, "window": 30 },
  "series_index": 0,
  "date_from": "-30d"
}
```

- `insight` takes the numeric ID or the short ID.
- `date_from` and `series_index` apply to trends insights.
  For a SQL insight, pass `config` with the `HogQLAlertConfig` instead.
- Leave out `evaluation_delay_intervals` unless the insight is a time-series trends insight and the alert will use the same delay.

## Common refusals

| Refusal                                                                          | Cause and fix                                                                                                                |
| -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Error on the `alert` field about the plan's alert limit                          | The project is at its plan's alert limit. Do not retry. Show the user the existing alerts and offer to change or delete one. |
| Error on `calculation_interval`                                                  | The plan does not include that cadence. Offer `hourly`.                                                                      |
| `detector_config.operator`: expected `"and"` or `"or"`                           | Send the ensemble operator in lowercase.                                                                                     |
| "Invalid detector configuration."                                                | `type` is missing or wrong, or the config has a field that type does not accept. Check the parameter table above.            |
| "... must be between ..."                                                        | A detector parameter is out of range. Use the range the message names.                                                       |
| Error on `evaluation_delay_intervals`                                            | The delay works only on time-series trends insights, and needs `check_ongoing_interval: false`. Set it to 0 or remove it.    |
| "Alert has invalid condition"                                                    | `condition` is missing. Send `{"type": "absolute_value"}` or a relative type.                                                |
| "Unsupported alert config type" or "requires a ... insight"                      | `config` is missing, or its `type` does not match the insight kind.                                                          |
| "At least one of lower or upper"                                                 | A threshold alert needs a bound. Add one, or add a `detector_config`.                                                        |
| "Lower threshold must be less than upper threshold"                              | Swap the bounds.                                                                                                             |
| "Absolute value alerts require an absolute threshold"                            | Use `"type": "absolute"` in the threshold with `absolute_value`.                                                             |
| "series_index ... is out of range"                                               | The index counts from 0, and counts formula results when the insight has formulas.                                           |
| "check_ongoing_interval is only supported ... when upper threshold is specified" | Turn off `check_ongoing_interval`, or use an upper bound.                                                                    |
| "Anomaly detection isn't supported for non time series trends"                   | The insight shows a single number or a pie. Change its display to a time series, or use a threshold alert.                   |
| "The AI detector is not enabled for your account."                               | The rollout is off for this organization. Offer a statistical detector.                                                      |
| "AI data processing is turned off"                                               | An organization admin can turn it on in organization settings. Until then, offer a statistical detector.                     |
| "already has N of M alerts using the AI detector"                                | The project is at its AI detector cap. The user can disable one, or use a statistical detector.                              |
| "The AI detector does not support breakdown insights yet"                        | Use an insight without a breakdown, or a statistical detector.                                                               |
