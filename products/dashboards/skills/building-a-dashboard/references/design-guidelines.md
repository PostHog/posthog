# Dashboard design guidelines

A dashboard is read top to bottom by someone who did not build it.
These rules make it answer one question fast, then let the reader dig.
Apply them to every dashboard, with or without a blueprint.

[tile-recipes.md](./tile-recipes.md) has the query JSON for every tile type named here.

## Start from one question

- Write the question the dashboard answers before you choose a tile, for example "Is onboarding getting better?".
  One dashboard serves one question and one audience.
- Put that question first in the dashboard description. Then say who is counted and who is excluded. Then say how to read it.
  Example: "Is checkout getting more reliable? Production traffic only, internal users excluded, complete weeks only. Compare each payment method before and after a release."
- If the request covers several questions or audiences, build a set: one overview dashboard and one dashboard per area.
  Give the set a shared name prefix and the same structure, and tell the user you are building a set.
  When several dashboards differ only by site, customer, or feature, build one, confirm it with the user, then repeat it.

## Order the page: summary first, evidence last

1. A headline row of numbers.
2. Sections, each on one theme. Inside a section, show the trend first, then the breakdown that explains it.
3. Raw rows a person reads (recent failures, top accounts) at the end of the section they support.

Every headline number needs a section below that explains it.
A section with no headline number is fine when it answers part of the dashboard's question.

## Headline row

- Use 3 or 4 number tiles in the first row: four tiles of `w: 3, h: 3` or three of `w: 4, h: 3`.
- Use a TrendsQuery with `trendsFilter.display: "Metric"`. The tile shows the number, a change, and a sparkline.
  Set `metricColorByDirection: true` so the sparkline shows direction.
- Name each headline tile in three words at most. A longer name is cut off.
- Put the overall number first. The other tiles are its parts, or the next numbers the reader asks about.
- **Every headline number must be exact.** If a number can only be estimated, leave it out of the row and let its section carry the exact version.
- **Use one kind of change for the whole row,** so that every pill means the same thing:
  - **The last complete period.** Set the interval to the dashboard's rhythm and `metricSummary: "latest"`. The tile shows the last complete week or day, and the change from the first period in the range to the last. This is the only correct form for unique users and for rates, and it also works for counts.
  - **This period against the previous one.** Set `compareFilter.compare: true` with `metricSummary: "total"`. Use it only when every tile in the row counts events. A total of daily unique users counts the same person once per day, and a total of daily rates means nothing.
- A rate belongs in the headline row only when both parts come from the same events in the same interval, such as an error rate.
  Show it with `metricSummary: "latest"`, which is exact for that one period. Do not use `"average"`: it gives every interval the same weight, whatever its volume.
  A rate that follows a cohort over time (activation, conversion, retention) cannot be computed by a trends formula. It belongs in a funnel or retention tile.
- For a number where lower is better (error rate, latency, cost), swap the red and green colors.
- Use `BoldNumber` only when a trend has no meaning, such as an all-time total.

## Sections

- Start each section with a heading tile: `posthog:dashboard-create-tile` with `type: "text"`, `body: "## Section name"`, and a `layouts.sm` box of `x: 0, w: 12, h: 1` at the section's `y`.
- Keep a section to 1-4 charts on one theme.
- When the dashboard covers several surfaces or segments (pages, features, platforms, plans), give each its own section with the same charts in the same order.
  The reader learns the shape once and compares sections at a glance.

## Grid

The desktop grid has 12 columns. Use only these rows:

| Row          | Tiles                          | Box for each tile |
| ------------ | ------------------------------ | ----------------- |
| Heading      | 1 text tile                    | `w: 12, h: 1`     |
| Headline     | 4 numbers (or 3 with `w: 4`)   | `w: 3, h: 3`      |
| Three across | 3 small charts that form a set | `w: 4, h: 4`      |
| Pair         | 2 charts                       | `w: 6, h: 5`      |
| Full width   | 1 chart                        | `w: 12, h: 5`     |

- Every row fills all 12 columns, and the tiles in a row have the same height.
- Use the full-width row for the chart with the most series, or the one the section is about.
- Use three across for a set that the reader compares side by side, such as mean, p95, and p99 of the same measure.
- The API stores boxes as sent and does not resolve overlaps. Compute `y` as a running total: each row starts at the previous row's `y` plus its `h`.

Example for a headline row, then one section with a pair and a full-width chart:

```text
y=0   four numbers        x=0,3,6,9  w=3  h=3
y=3   heading             x=0        w=12 h=1
y=4   two charts          x=0,6      w=6  h=5
y=9   one chart           x=0        w=12 h=5
y=14  next heading        x=0        w=12 h=1
```

## Choose each chart

- Change over time: a line chart. This is the default tile.
- A rate over time: a line chart with a percent axis.
- Categories compared as totals ("top pages", "failures by reason"): `ActionsBarValue`.
- Step conversion: a funnel with `funnelVizType: "steps"`. Conversion over time: the same funnel with `funnelVizType: "trends"`.
- Whether people come back: a retention insight.
- A table: only for rows a person reads, such as a top-10 list or recent records. Put it beside the chart it explains.
- Use one breakdown per chart, and limit it to the values a reader can tell apart (5-10).
- Prefer a rate to a count when the denominator moves: percent of users, per active user, per 1,000 calls, conversion.
  A count that rises because traffic rose says nothing about quality.
- For durations and latency, show a high percentile (p95) beside the mean or median. The mean hides the slow tail.
- Do not use a pie chart for more than 4 values or for anything that changes over time.
- Use SQL only when no native insight can express the calculation. A SQL tile must read the dashboard date range through `{filters.dateRange.from}` and `{filters.dateRange.to}`, or it ignores the date picker.

## Show complete periods only

A period that is still in progress looks like a sudden drop, and the reader cannot tell it from a real one.

- Set a date range of whole periods on the dashboard: `date_from: "-12wStart"`, `date_to: "-1wEnd"` for weekly charts, or `date_from: "-29d"`, `date_to: "-1d"` for daily ones.
- On a funnel shown over time, set `hideIncompleteConversionWindowPeriods: true`.
- If the reader needs the period in progress, keep it and say in the dashboard description that the last point is partial.

## Finish every tile

- Name: say what is measured in plain words. Do not repeat the section name in it, and do not use a raw event name or the auto-generated name.
  Use a shared prefix only when sections repeat per surface ("Checkout: errors by reason", "Search: errors by reason").
- Description: two sentences at most. Give the definition (what is counted, or what is divided by what) and anything that is true only for this tile.
  Example: "Share of checkout attempts that returned an error, per day. Attempts retried within a minute count once."
  Scope that applies to every tile (production only, internal users excluded, the date range) goes in the dashboard description once. Do not repeat it on each tile.
- Hide the description on the tile. A description shown on a tile takes the room the chart needs, and on a headline tile it pushes the number out of view.
  Set `show_description: false` for every insight tile in the `posthog:dashboard-update` call that sets the layout. The text stays available from the tile's info popover.
- Series labels: set `custom_name` to plain words, for example "Server error (500)" instead of an event name with a filter.
- Units: format the axis as percent, duration, or currency, and set decimal places. See the `formatting-insight-axes` skill.
- Legend: show it when a line chart has a breakdown or more than one named series. Hide it for one series, and for a bar chart of totals, where each bar has its own label.
- Goal line: add one when there is a target or a known normal value, and label it.
- Noisy daily lines: use a weekly interval or `smoothingIntervals: 7`.

## One scope for the whole dashboard

- Count the same population on every tile.
  Set `filterTestAccounts: true` to exclude internal and test users, and filter to production when events carry an environment property.
- Count one thing: people or accounts, not people in one tile and accounts in the next.
- Set the default date range once, on the dashboard, with `posthog:dashboard-update` `filters`. It replaces each tile's own range, so every tile shows the same window.
- Use one interval for the tiles in a row.
- State the scope in the dashboard description, so the reader does not have to open a tile to learn it.

## Size

- A typical dashboard has 3-4 headline numbers and 2-4 sections: 8-14 insight tiles.
- More than 5 sections, or sections for different audiences, means the request is a set of dashboards.

## Build order

1. Run the heaviest query once before you build on it, usually the funnel or the unique-users trend. If it times out or runs out of memory, shorten the range or pick a lighter event. Do not retry it unchanged.
2. `posthog:dashboard-create` with the name, description, and tags.
3. `posthog:insight-create` for each tile, with `dashboards: [<id>]` so the insight lands on the dashboard. Keep the tile ID from each response.
4. `posthog:dashboard-create-tile` for each section heading, with its layout box.
5. One `posthog:dashboard-update` with the dashboard `filters` and, for every insight tile, its `layouts.sm` box and `show_description: false`.
6. `posthog:dashboard-insights-run` with `refresh: "blocking"` to confirm that each tile returns data. The default reads only the cache.

## When the data is not flowing yet

Dashboards are often built right after the events were added to the code.

- Build each tile on the exact event and property names from the code or tracking plan.
- Never substitute a different event so that a tile shows data.
- Say it in the dashboard description: which events the tiles wait for, and from which release.
  Remove that note when you next update the dashboard and the data has arrived.
- Tell the user which tiles are empty and why.

## Check before you report back

- The description opens with the question and states the scope.
- The first row is 3-4 exact numbers with short names, and every pill in it means the same thing.
- Every section has a heading, and every row fills 12 columns with no overlap.
- No chart ends in a period that is still in progress, unless the description says so.
- Every tile has a plain name, a short description that is hidden on the tile, labeled series, and a formatted axis.
- Rates are shown as rates, and each one is exact.
- `posthog:dashboard-insights-run` returned data, or the description says why a tile is empty.
