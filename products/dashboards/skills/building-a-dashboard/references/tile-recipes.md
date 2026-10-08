# Tile recipes

Query JSON for the tiles that dashboards use most.
Pass each one as `query` to `posthog:insight-create`, with `name`, `description`, and `dashboards: [<dashboard id>]`.
Replace the values in angle brackets. Everything else can stay as written.

These shapes are complete. You do not need to read a query tool's schema to use them.
Read a schema only for something these recipes do not cover, such as property filters or breakdowns.

The examples use the weekly rhythm. For a daily dashboard, change `interval` to `"day"` and the date range to `"-29d"` and `"-1d"`.

## Series

An event:

```json
{ "kind": "EventsNode", "event": "<event name>", "math": "total", "custom_name": "<plain label>" }
```

An action:

```json
{ "kind": "ActionsNode", "id": <action id>, "name": "<action name>", "math": "total", "custom_name": "<plain label>" }
```

Common `math` values:

| `math`                 | Counts                                                                           |
| ---------------------- | -------------------------------------------------------------------------------- |
| `total`                | Events                                                                           |
| `dau`                  | Unique users in each interval. With `interval: "week"` it is weekly unique users |
| `weekly_active`        | Unique users in the trailing 7 days, at each daily point                         |
| `first_time_for_user`  | Users who did this for the first time ever. Heavy on a large project             |
| `first_time_for_group` | Accounts that did this for the first time ever. Also set `math_group_type_index` |
| `unique_group`         | Unique accounts. Also set `math_group_type_index` to the group type index        |
| `unique_session`       | Unique sessions                                                                  |

## Counting accounts instead of people

Find the group type index with `posthog:project-get`.

- Trends and stickiness: on each series, set `"math": "unique_group"` and `"math_group_type_index": <group type index>`.
- Funnel, lifecycle, and retention: beside `kind`, set `"aggregation_group_type_index": <group type index>`.

## Test a query before you save it

Pass the same JSON to the matching query tool: `posthog:query-trends`, `posthog:query-funnel`, `posthog:query-lifecycle`, `posthog:query-stickiness`, or `posthog:query-retention`.

## Headline number: the last complete period

```json
{
  "kind": "TrendsQuery",
  "interval": "week",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [{ "kind": "EventsNode", "event": "<event name>", "math": "dau", "custom_name": "Active users" }],
  "trendsFilter": { "display": "Metric", "metricSummary": "latest", "metricColorByDirection": true }
}
```

The tile shows the last complete week, a sparkline of the range, and the change from the first week to the last.
Do not set `compareFilter` on a `latest` tile. It is ignored and doubles the query.

## Headline number: a rate

A rate is exact only inside one period, so show the last complete period with `latest`.
Do not use `metricSummary: "average"` for a rate. It gives every interval the same weight, whatever its volume.

```json
{
  "kind": "TrendsQuery",
  "interval": "week",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [
    { "kind": "EventsNode", "event": "<attempt event>", "math": "total", "custom_name": "Attempts" },
    { "kind": "EventsNode", "event": "<failure event>", "math": "total", "custom_name": "Failures" }
  ],
  "trendsFilter": {
    "display": "Metric",
    "formulaNodes": [{ "formula": "B/A", "custom_name": "Error rate" }],
    "aggregationAxisFormat": "percentage_scaled",
    "decimalPlaces": 1,
    "metricSummary": "latest",
    "metricColorByDirection": true,
    "metricChangeIncreaseColor": "#db3707",
    "metricLineIncreaseColor": "#db3707",
    "metricChangeDecreaseColor": "#388600",
    "metricLineDecreaseColor": "#388600"
  }
}
```

The four color fields flip red and green for a number where lower is better. Leave them out when higher is better.

## Headline number: this period against the previous one

Use this only for a count of events. The total of a period and the total of the period before it are both exact.

```json
{
  "kind": "TrendsQuery",
  "interval": "day",
  "dateRange": { "date_from": "-29d", "date_to": "-1d" },
  "filterTestAccounts": true,
  "compareFilter": { "compare": true },
  "series": [{ "kind": "EventsNode", "event": "<event name>", "math": "total", "custom_name": "Orders" }],
  "trendsFilter": { "display": "Metric", "metricSummary": "total", "metricColorByDirection": true }
}
```

## Line chart

```json
{
  "kind": "TrendsQuery",
  "interval": "week",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [{ "kind": "EventsNode", "event": "<event name>", "math": "dau", "custom_name": "Active users" }],
  "trendsFilter": { "display": "ActionsLineGraph", "showLegend": false }
}
```

For several series, add them to `series` and set `showLegend: true`.
For a rate, add two series and the `formulaNodes`, `aggregationAxisFormat`, and `decimalPlaces` fields from the rate recipe above.

## Totals compared as bars

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [
    { "kind": "EventsNode", "event": "<event one>", "math": "dau", "custom_name": "<plain label>" },
    { "kind": "EventsNode", "event": "<event two>", "math": "dau", "custom_name": "<plain label>" }
  ],
  "trendsFilter": { "display": "ActionsBarValue", "showLegend": false }
}
```

Each bar carries its own label, so the legend stays off.

## Funnel

```json
{
  "kind": "FunnelsQuery",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [
    { "kind": "EventsNode", "event": "<first step event>", "custom_name": "Signed up" },
    { "kind": "EventsNode", "event": "<last step event>", "custom_name": "Activated" }
  ],
  "funnelsFilter": {
    "funnelVizType": "steps",
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day"
  }
}
```

Set the window to the time a person may reasonably take.
To count accounts instead of people, add `"aggregation_group_type_index": <group type index>` beside `kind`.

## Funnel conversion over time

The same funnel, with three changes:

```json
{
  "kind": "FunnelsQuery",
  "interval": "week",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [
    { "kind": "EventsNode", "event": "<first step event>", "custom_name": "Signed up" },
    { "kind": "EventsNode", "event": "<last step event>", "custom_name": "Activated" }
  ],
  "funnelsFilter": {
    "funnelVizType": "trends",
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day",
    "hideIncompleteConversionWindowPeriods": true
  }
}
```

`hideIncompleteConversionWindowPeriods` removes the recent periods whose window is still open. Without it the line always falls at the right edge.
`posthog:query-funnel` ignores this field, so a test run still shows the falling tail. `posthog:insight-create` keeps it, and the saved tile is correct.

## Lifecycle

```json
{
  "kind": "LifecycleQuery",
  "interval": "week",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [{ "kind": "EventsNode", "event": "<core action event>", "custom_name": "Active users" }],
  "lifecycleFilter": { "showLegend": true }
}
```

## Stickiness

Use the dashboard's rhythm as the interval, so the chart reads "weeks active out of 12" and not 84 daily bars.

```json
{
  "kind": "StickinessQuery",
  "interval": "week",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "series": [{ "kind": "EventsNode", "event": "<core action event>", "custom_name": "Active users" }]
}
```

## Retention

```json
{
  "kind": "RetentionQuery",
  "dateRange": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "filterTestAccounts": true,
  "retentionFilter": {
    "period": "Week",
    "totalIntervals": 8,
    "retentionType": "retention_first_time",
    "targetEntity": { "id": "<signup event>", "name": "<signup event>", "type": "events" },
    "returningEntity": { "id": "<core action event>", "name": "<core action event>", "type": "events" }
  }
}
```

For an action, use `{ "id": <action id>, "name": "<action name>", "type": "actions" }`.
Keep `totalIntervals` below the number of periods in the date range, or the last columns stay empty.

## SQL tile

Use SQL only when no query above can express the calculation.
Read the date range from the dashboard, so that the tile follows the date picker like its neighbors:

```sql
SELECT toStartOfWeek(timestamp, 1) AS week, count() AS events
FROM events
WHERE event = '<event name>'
  AND timestamp >= {filters.dateRange.from}
  AND timestamp < {filters.dateRange.to}
GROUP BY week
ORDER BY week
```

A SQL tile cannot use the `Metric` display, so it cannot be a headline number with a comparison.

## Section heading

`posthog:dashboard-create-tile`:

```json
{ "id": <dashboard id>, "type": "text", "body": "## Growth", "layouts": { "sm": { "x": 0, "y": 3, "w": 12, "h": 1 } } }
```

## Layout, scope, and hidden descriptions in one call

`posthog:insight-create` lists the new tile under `dashboard_tiles`, and `posthog:dashboard-create-tile` returns its tile's ID, so you do not need `posthog:dashboard-get` to find them.

`posthog:dashboard-update`:

```json
{
  "id": <dashboard id>,
  "filters": { "date_from": "-12wStart", "date_to": "-1wEnd" },
  "tiles": [
    { "id": <tile id>, "show_description": false, "layouts": { "sm": { "x": 0, "y": 0, "w": 3, "h": 3 } } },
    { "id": <tile id>, "show_description": false, "layouts": { "sm": { "x": 3, "y": 0, "w": 3, "h": 3 } } }
  ]
}
```

## Check the result

`posthog:dashboard-insights-run` with `{ "id": <dashboard id>, "refresh": "blocking" }`.
The default reads only the cache, and a tile that has never been computed comes back empty.
On a dashboard with heavy tiles, pass a few tiles per call: `"tile_ids": "123,456,789"`, one comma-separated string.
