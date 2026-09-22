# Metrics dashboard panels

The metrics viewer and metrics dashboard tiles render one of several panel types, picked from the chart-type dropdown.
The picker lists the time-series panels (line, area, bar) plus the Grafana-style scalar and categorical panels (stat, gauge, bar gauge, table).
The scalar panels are gated behind the `metrics-dashboard-panels` feature flag.

Every panel reads the same response: a list of series, each with a label set, bucketed points, and an optional UCUM unit.

## How a panel collapses points to a number

Scalar panels (stat, gauge, bar gauge) and the table's reducer columns collapse each series to one number with a reducer: `last`, `mean`, `min`, `max`, `sum`, or `delta` (last minus first).
The `reduce` display setting chooses the reducer; the deprecated `statSummary` maps onto it (`latest` → `last`, `average` → `mean`, `total` → `sum`).
A series whose buckets are all null reduces to null and is dropped by the scalar panels, so a tile shows "No data" instead of a dash.

## Units

The display `unit` setting overrides everything.
Without it, a series renders with its ingested UCUM unit — but only when no other series in the same tile carries a different unit.
A tile mixes every series' values on one chart, so a mixed-unit result renders bare numbers rather than mislabel one series with another's unit.
UCUM `1` (dimensionless) renders as a plain number: it is not necessarily a ratio, so it is never rescaled to a percent.

## Thresholds

Thresholds color the scalar panels and the table's value cells.
Each step is a lower bound with a color token; the lowest step is the base color.
They are a color scale, not the range: the gauge's automatic max extends past the highest threshold when the value does, so the arc never reads full while the number keeps climbing.

## Panel-specific rules

- **Stat**: one headline card per series (capped at 12) with a sparkline.
- **Gauge**: one radial gauge per series (capped at 12). Bounds come from the explicit y-axis min/max, else the threshold extremes, else 0 to the value.
- **Bar gauge**: one bar per series, sorted by value. It needs grouped data to be meaningful, so the picker disables it unless the result is grouped; removing the last group-by falls the display back to line.
- **Table**: one row per series, one column per label key, plus one column per reducer in `legendCalcs`. The list is deduplicated and capped at six reducers — it is persisted user input from saved insights.

## Null buckets

A null bucket is a non-representable aggregate (a gap).
The time-series panel renders it as 0 until the chart library takes null data; `nullMode` is read by the chart config, not the panel.
The reducers skip nulls rather than counting them as zero, so a gap never drags a `mean` down.
