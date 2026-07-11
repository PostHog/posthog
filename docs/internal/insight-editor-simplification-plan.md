# Simplifying the product analytics insight editor

Users regularly report that the insight editor has too many options, too much going on, and feels overwhelming.
This document is a data-driven plan for reducing that overload: what to hide by default, what to consolidate, and what to consider scrapping.

It is based on 30 days of our own product usage data (July 2026) from the PostHog App + Website project:

- `insight analyzed` / `insight viewed` / `insight saved` events, whose `sanitizeQuery()` properties encode which features a query uses (`has_formula`, `breakdown_type`, `compare`, `display`, `funnel_viz_type`, `funnel_order_type`, `interval`, ...)
- `insight type tab clicked` and `editor panel section toggled` events
- `$autocapture` clicks on `/insights/` pages, correlated to editor controls via `data-attr` values in `elements_chain`, and via element label text for controls that lack a `data-attr`

Per public-repo policy, this document uses qualitative usage tiers instead of raw figures.
The queries in the appendix reproduce the exact numbers against the internal project.

A live, auto-refreshing version of this analysis is available internally as the
[Insight editor usage audit dashboard](https://us.posthog.com/project/2/dashboard/1833172)
(PostHog staff only), covering insight types analyzed/clicked/saved, chart display types,
trends feature adoption, funnel modes, editor sections, math options, Options-menu toggles,
and rarely used advanced controls, each on a rolling 30-day window.

## Usage tiers

Relative to the population of users who viewed or edited an insight in the window:

| Tier | Meaning |
| --- | --- |
| **Core** | Used by roughly half or more of insight users |
| **Healthy** | Used by roughly one in ten |
| **Niche** | Used by a few percent |
| **Negligible** | Used by well under one percent |
| **Dead** | A handful of users or effectively zero |

## Headline findings

1. **Trends and Funnels are the product.** Together they account for the overwhelming majority of insights analyzed and saved. Retention is a clear but distant third. Paths, Lifecycle, and Stickiness are all niche.
2. **The minor insight tabs attract clicks but not usage.** Retention, Paths, Stickiness, and Lifecycle tabs each get clicked by thousands of curious users, but the click-to-save conversion collapses as you go down the list. Stickiness converts worst by a wide margin: most users who open the tab never analyze a stickiness insight, let alone save one. Paths and Lifecycle are nearly as bad. This is the strongest "too much going on" signal in the data: the tab row promises six equally-weighted analyses, and four of them mostly produce abandonment.
3. **A handful of editor features carry all the weight.** Series + event picker, property filters, breakdown, date range, filter test accounts, and the chart type picker are core. Formulas and compare-to-previous are healthy. Nearly everything else is niche or below.
4. **The long tail is very long.** The math dropdown alone exposes 30+ options; the bottom ~15 (percentile variants, per-group actor counts) are each negligible. The Options menu exposes ~18 toggles; the bottom ten are negligible-to-dead. Several controls recorded zero clicks in a month.
5. **Some things are already dead and just need burying.** Sampling (already deprecated) shows effectively zero new usage. The flag-gated Hog insight tab recorded zero clicks. The time-to-convert bin picker recorded zero clicks. "Show alert anomaly points" was clicked by a couple of users.

## Feature-by-feature usage map

### Insight types (analyzed → saved, per type)

| Type | Analyzed usage | Tab click → save conversion | Notes |
| --- | --- | --- | --- |
| Trends | Core | High (it's the default) | |
| Funnels | Core | High | |
| SQL / HogQL | Healthy | n/a (separate editor) | Analyzed often, rarely saved as insights (users likely save as views/endpoints instead) |
| Retention | Healthy | Medium | |
| Lifecycle | Niche | Low | Single-series only; conceptually a Trends mode |
| Paths | Niche | Very low | Heavy tab interest, poor conversion |
| Stickiness | Negligible | Worst of all types | An order of magnitude fewer users than Retention |

### Trends features

| Feature | Tier |
| --- | --- |
| Property filters on series / global filters | Core |
| Breakdown | Core (about half of trends users) |
| Filter test accounts | Core |
| Chart type picker | Core |
| Interval picker (day/week/month/hour) | Core |
| Formula mode | Healthy |
| Compare to previous period | Healthy |
| Multiple breakdowns | Healthy (within breakdown users) |
| Minute interval | Niche |
| Quarter/year intervals (flag-gated) | Dead |
| Sampling factor | Dead (deprecation already in progress) |

### Chart display types (Trends)

| Display | Tier |
| --- | --- |
| Line | Core (dominant by a large multiple) |
| Bar variants, Number, Table, Pie | Healthy |
| Area, Cumulative line, World map | Niche |
| Metric, Calendar heatmap, Box plot, Slope graph (all flag-gated) | Negligible (caveat: gated rollout suppresses these numbers) |
| `ActionsStackedBar` enum value | Dead code – not selectable in the menu at all, still in the enum |

Stickiness insights use the line chart almost exclusively; every other display type on Stickiness is dead.

### Math / aggregation options

| Option | Tier |
| --- | --- |
| Unique users, Total count | Core |
| Property value (avg/sum), Count per user (avg/median), Unique sessions, First time for user | Healthy-to-niche |
| WAU, MAU, HogQL expression | Niche |
| First matching event, First time with filters, Unique groups | Negligible |
| Percentile variants (P75/P90/P95/P99, both for property values and count-per-user – 8 menu entries) | Negligible (each is in the bottom tier; median is the only midpoint stat with real usage) |
| Min/Max (property value and count-per-user) | Negligible |

### Options menu (display toggles)

Only a modest minority of trends users ever open the Options menu at all.
Within it:

| Toggle | Tier |
| --- | --- |
| Show values on series, Show legend | Healthy (relative to menu openers) |
| Show trend lines, Show as % of total | Niche |
| Multiple Y-axes, Alert threshold lines, Goal lines, Annotations, Hide weekends, Stack breakdown values, Y-axis unit/scale, Decimal places | Negligible |
| Show total below chart, Show percentages on series, Stack bars (lifecycle) | Negligible |
| Moving average, Confidence intervals, Show change (Metric) | Dead |
| Show alert anomaly points | Dead (single-digit clicks in a month) |
| Axis label inputs | Zero autocapture interactions (text inputs, so weak signal, but consistent with dead) |

### Funnels features

| Feature | Tier |
| --- | --- |
| Steps builder, breakdown | Core |
| Conversion window, step order, conversion-rate reference, breakdown attribution | Niche (each touched by a small fraction of funnel users; the collapsed "Funnel settings" section is doing its job) |
| Historical trends viz | Niche |
| Time to convert viz | Negligible |
| Time-to-convert bin picker | Dead (zero clicks) |
| Strict step order | Negligible |
| Unordered steps | Negligible |
| Exclusion steps | Negligible (many open the section, almost nobody completes an exclusion) |

### Retention features

| Feature | Tier |
| --- | --- |
| Retention condition (target/returning/period) | Core (for retention users) |
| Breakdown | Negligible |
| "Calculation options" section | Opened by ~1 in 6 retention users |
| Calculate-by property aggregation (flag-gated) | Negligible |
| Mean calculation mode, time-window mode, minimum occurrences, cumulative mode, reference picker | Individually negligible (no data-attrs on most; section-open rate is the ceiling) |

### Paths features

| Feature | Tier |
| --- | --- |
| Start/end point pickers | Core (for paths users) |
| Event type toggles | Healthy (for paths users) |
| Exclusions | Niche |
| SQL expression path type | Negligible |
| Wildcard groups, edge limits, path cleaning (paygated advanced) | Negligible |

## Recommendations

Ordered by confidence and effort. Every removal or default change should ship behind a feature flag with a holdout, watching `insight saved` rate, editor abandonment, and support ticket volume as guardrails.

### P0 – Bury the dead (low effort, near-zero risk)

1. **Remove the "Show alert anomaly points" toggle.** Dead. Fold it into "Show alert threshold lines" if we want to keep the capability.
2. **Finish removing sampling.** It is already deprecated with a notice banner; new usage is effectively zero. Delete the UI remnants and the `samplingFactor` plumbing from the editor.
3. **Delete the flag-gated Hog insight tab.** Zero clicks; the flag has been parked for a long time.
4. **Remove the time-to-convert bin picker.** Zero clicks in a month. Auto-bin instead.
5. **Remove the "Statistical analysis" block (confidence intervals + moving average) from the Options menu**, or collapse it to a single entry. Both toggles are dead.
6. **Clean up the `ActionsStackedBar` enum value** (not selectable, still handled everywhere).
7. **Decide on the quarter/year interval flag.** Usage in the flag cohort is dead; either kill the flag or ship it silently without menu prominence.

### P1 – Consolidate the long tails (medium effort, high visible impact)

8. **Collapse the percentile math options.** Replace the eight P75/P90/P95/P99 entries (property value + count per user) with a single "Percentile" entry that opens a small value picker (75/90/95/99, or free input). This alone removes ~25% of the math menu surface while keeping the capability. Same treatment can merge Min/Max into the picker.
9. **Group the "first time" math variants.** "First time for user", "First time for user with filters", and "First matching event for user" read as three near-identical rows; make one "First occurrence" entry with a qualifier.
10. **Tier the Options menu.** Keep the proven toggles at top level (Show values on series, Show legend, Show trend lines, Show as % of total, Y-axis unit) and move everything else behind a "More display options" sub-entry. Ten-plus negligible toggles is where most of the "too much going on" perception comes from once users open that menu.
11. **Per-type chart pickers.** Stickiness should offer line and bar only. Lifecycle needs no picker. Trends keeps the full set but ordered by usage, with the flag-gated types (Metric, Calendar heatmap, Box plot, Slope graph) held to a higher bar before GA: their gated cohorts already show weak engagement.
12. **Fold the time-to-convert visualization into the steps view.** The steps table already shows median time between steps; a per-step distribution popover would serve the negligible time-to-convert audience without a third top-level funnel mode. This reduces the funnel graph-type picker to Steps / Historical trends.
13. **Consolidate Retention's "Calculation options".** Keep "relative to" and cumulative mode visible; merge mean mode, time-window mode, and minimum occurrences into one compact "Advanced" popover. Reassess the flag-gated calculate-by-property aggregation before investing further.

### P2 – Rethink the insight type row (high effort, highest ceiling)

14. **Stop presenting six insight types as equals.** Usage says the row should read: Trends, Funnels, Retention, then a "More" group holding Paths, Lifecycle, Stickiness. The minor types generate exploratory clicks followed by abandonment, which is exactly the overwhelm users describe.
15. **Merge Stickiness into Trends.** It is already restricted to actor math and one config (stickiness criteria + cumulative mode); it could be a Trends mode or math option ("days active per interval") instead of a whole insight type. It is the least-used type by an order of magnitude while occupying equal navigation weight.
16. **Consider Lifecycle as a Trends display mode.** Single-series only, no breakdown, no formula: it behaves like a display option today, and its four toggles (new/returning/resurrecting/dormant) map cleanly onto series visibility.
17. **Fix Paths' first-run experience rather than its option count.** Paths has heavy tab interest and the worst-in-class conversion after Stickiness. The advanced options are already paygated/collapsed; the problem is more likely the empty default state and the cost of configuring start/end points. A sensible default (pageview paths ending at the current project's most common exit) would do more than removing controls. Hide the SQL path type behind the advanced section.

### P3 – Instrumentation gaps to close first

These make the next round of this analysis cheaper and more precise:

18. **Add `data-attr`s to every Options-menu toggle.** Today they are only trackable via label text, which breaks on copy changes.
19. **Record math types in `sanitizeQuery()`.** We can see math *clicks* via autocapture but not which math a viewed/saved insight actually uses; add a `math_types` array to the sanitized query properties in `eventUsageLogic.ts`.
20. **Record advanced-option state on `insight saved`.** Booleans for exclusions, custom conversion window, step order, attribution, retention calc options would separate "clicked once" from "relied upon".

## What not to touch

Breakdowns, property filters, filter test accounts, the date/interval pickers, formulas, and compare-to-previous all show core or healthy adoption.
The collapsed editor sections (Filters, Breakdown, Advanced options, Funnel settings) are opened frequently and in proportion to their contents' usage; the collapse pattern itself is working.

## Measurement caveats

- Autocapture measures 30 days of *clicks*, not reliance: a feature configured once on a long-lived saved insight shows no clicks. The `insight analyzed` properties partially correct for this because they fire on every view of saved insights too.
- Flag-gated features have usage suppressed by their rollout percentage; treat their tiers as lower bounds and check the flag cohort before deciding.
- Text inputs (axis labels, formula box) autocapture weakly; corroborate with query properties before acting on zeros.
- This is one project's window; rerun the appendix queries over a quarter before shipping removals.

## Appendix: reproduction queries

Run against the PostHog App + Website project. All queries are 30-day windows.

Insight type distribution:

```sql
SELECT properties.query_source_kind AS kind, count() AS analyzed, count(DISTINCT person_id) AS users
FROM events
WHERE event = 'insight analyzed' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY kind ORDER BY analyzed DESC
```

Feature adoption per type (formula, breakdown, compare, test accounts, sampling):

```sql
SELECT properties.query_source_kind AS kind,
       count() AS n,
       uniqIf(person_id, properties.has_formula = 'true') AS formula_users,
       uniqIf(person_id, isNotNull(properties.breakdown_type)) AS breakdown_users,
       uniqIf(person_id, properties.compare = 'true') AS compare_users,
       uniqIf(person_id, properties.filter_test_accounts = 'true') AS fta_users,
       countIf(isNotNull(properties.samplingFactor)) AS sampling_events
FROM events
WHERE event = 'insight analyzed' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY kind ORDER BY n DESC
```

Display type, funnel viz/order, and interval distributions: same query shape, grouping by `properties.display`, `properties.funnel_viz_type` + `properties.funnel_order_type`, or `properties.interval`.

Tab clicks vs saves:

```sql
SELECT properties.insight_type AS t, count() AS clicks, count(DISTINCT person_id) AS users
FROM events
WHERE event = 'insight type tab clicked' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY t ORDER BY clicks DESC
```

Collapsed section engagement:

```sql
SELECT properties.section AS section, properties.action AS action, count(), count(DISTINCT person_id)
FROM events
WHERE event = 'editor panel section toggled' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY section, action ORDER BY 3 DESC
```

Control-level clicks via autocapture (`data-attr` extraction, index-normalized):

```sql
SELECT replaceRegexpAll(extract(elements_chain, 'attr__data-attr="([^"]+)"'), '-\\d+$', '') AS da,
       count() AS clicks, count(DISTINCT person_id) AS users
FROM events
WHERE event = '$autocapture'
  AND timestamp >= now() - INTERVAL 30 DAY
  AND properties.$current_url LIKE '%/insights/%'
  AND extract(elements_chain, 'attr__data-attr="([^"]+)"') != ''
GROUP BY da ORDER BY clicks DESC LIMIT 200
```

Options-menu toggles (no data-attrs, matched by label):

```sql
SELECT properties.$el_text AS label, count() AS clicks, count(DISTINCT person_id) AS users
FROM events
WHERE event = '$autocapture'
  AND timestamp >= now() - INTERVAL 30 DAY
  AND properties.$current_url LIKE '%/insights/%'
  AND properties.$el_text IN ('Options', 'Show values on series', 'Show legend', 'Show trend lines',
    'Show as % of total', 'Show alert threshold lines', 'Show multiple Y-axes', 'Show annotations',
    'Hide weekend data', 'Stack breakdown values', 'Add goal line', 'Show total below chart',
    'Show percentages on series', 'Stack bars', 'Show moving average', 'Show confidence intervals',
    'Show change', 'Show alert anomaly points')
GROUP BY label ORDER BY clicks DESC
```
