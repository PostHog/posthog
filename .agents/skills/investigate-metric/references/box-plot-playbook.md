# Box plot metrics playbook

For TrendsQuery insights rendered as a box plot (`trendsFilter.display = "BoxPlot"`).
The metric isn't a count — it's the distribution of a numeric `math_property` per time
bucket (min, p25, median, mean, p75, max). "Dropped" can mean median fell, IQR widened
or narrowed, the upper-tail outliers disappeared, or mean/median diverged (skew shift).

Box plots do **not** support `breakdownFilter` (`BoxPlot` is listed in
`NON_BREAKDOWN_DISPLAY_TYPES`; the backend drops the filter silently). Segmentation and
tail-targeted actor drilldown therefore route through HogQL.

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes.

## 1. Identify which statistic moved

Rerun `posthog:query-trends` with the original BoxPlot TrendsQuery. Read `boxplot_data`
per bucket and classify the shift before hypothesizing a cause:

- **Median drop / spike** — typical behavioral change in the middle of the population.
- **IQR widened** — the middle 50% spread out; often a new slow segment appeared.
- **IQR narrowed** — spread compressed; often a fast or slow tail was removed (feature
  gate, rate limit, outage of a slow dependency).
- **Upper-tail outliers disappeared / appeared** — a specific extreme cohort entered or
  left; test by toggling `trendsFilter.excludeBoxPlotOutliers`. If the shift vanishes
  with outliers excluded, the delta is outlier-driven; if it persists, the bulk of the
  population moved.
- **Mean / median divergence** — skew changed; the tails are pulling the mean without
  moving the center.

Record which statistic(s) moved — the next steps differ for tail-driven vs bulk shifts.

## 2. Zoom the anomaly window

Apply the **interval zoom** recipe from shared-patterns. Rerun at `interval: "hour"` on
a tight window. A single-hour IQR compression typically pins the shift to a deploy or
incident; a sustained shift suggests a broader population or tracking change.

## 3. Segment without breakdowns

Because `breakdownFilter` is ignored for box plots, substitute with one of:

**a. Parallel TrendsQuery series.** One series per candidate segment value, each with
an `EventsNode` filtered via `properties`:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "trendsFilter": { "display": "BoxPlot" },
  "series": [
    {
      "kind": "EventsNode",
      "event": "checkout_completed",
      "math": "p75",
      "math_property": "order_value",
      "properties": [{ "type": "event", "key": "plan", "value": "free", "operator": "exact" }]
    },
    {
      "kind": "EventsNode",
      "event": "checkout_completed",
      "math": "p75",
      "math_property": "order_value",
      "properties": [{ "type": "event", "key": "plan", "value": "paid", "operator": "exact" }]
    }
  ]
}
```

**b. HogQL quantile template** — see [shared-patterns.md](./shared-patterns.md#hogql-quantile-template).
Grouping by segment + time bucket returns per-segment quartiles in one query, which
scales better than one series per value when the segment has many values.

Pick candidate segment properties via shared-patterns **property discovery** and the
**breakdown dimensions** menu (plan, country, app_version, `$feature/<flag>`, etc.).
Apply **interpreting breakdown results** — a p75 swing on a small series is often noise;
check the segment's volume alongside its quartiles.

## 4. Actor drilldown at the tails

`posthog:query-trends-actors` takes `day` + optional `breakdown` — it cannot select by
percentile, so it can't isolate the users responsible for a tail shift. Use
`posthog:execute-sql` with the quantile filter pattern, for example:

```sql
SELECT distinct_id, max(toFloat(properties.order_value)) AS max_value
FROM events
WHERE event = 'checkout_completed'
  AND timestamp >= '2026-04-15 00:00:00'
  AND timestamp <  '2026-04-16 00:00:00'
  AND toFloat(properties.order_value) > (
    SELECT quantile(0.9)(toFloat(properties.order_value))
    FROM events
    WHERE event = 'checkout_completed'
      AND timestamp >= '2026-04-15 00:00:00'
      AND timestamp <  '2026-04-16 00:00:00'
  )
GROUP BY distinct_id
ORDER BY max_value DESC
LIMIT 50
```

Mirror the template for the lower tail when IQR narrowed (`< quantile(0.1)(...)`).
Feed the returned IDs into `posthog:query-session-recordings-list` for UI-shaped shifts
— see shared-patterns **session recordings**.

## 5. Cross-check against errors / logs

Apply the **error / logs cross-check** pattern from shared-patterns. For box plots, the
relevant question is usually whether a failure mode truncated a distribution (timeouts
killed the slow tail, a validation error blocked expensive orders). Confirm with the
three checks — timing, plausible mechanism, user overlap.

## 6. Check for a cohort-composition change

`posthog:query-lifecycle` on the same event:

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "day",
  "series": [{ "kind": "EventsNode", "event": "checkout_completed" }]
}
```

Distribution shifts frequently reflect a mix change rather than behavior change — an
influx of new free-tier users can pull a p75 order value down while no existing user
changed behavior. If lifecycle shows a composition shift aligned with the anomaly
window, reframe the finding around cohort mix.
