---
name: creating-exploration-dashboards
description: |
  Generate, create, build, scaffold, or set up a tailored multi-tile PostHog dashboard for a topic. Inspects the project's actual event/property taxonomy and assembles 4–8 tiles grounded in that data — not a generic template. Use when the user says "create a [retention | acquisition | funnel | engagement | feature-adoption | revenue] dashboard", "build me a dashboard for X", "make a dashboard around Y", "scaffold a dashboard", "generate a dashboard", "set up a starter dashboard, I just instrumented PostHog", or "show me a dashboard about Z". Do NOT use when the user references an existing dashboard by id/name/url, asks to update, summarise, share, or export one, picks a static template manually in the new-dashboard modal, only wants a single saved insight, or asks for a one-off report.
license: MIT
metadata:
  author: vasco
  category: dashboards
  feature: posthog-code-dashboards
---

# Creating exploration dashboards

You build a real, multi-tile PostHog dashboard for a topic the user names. Real means: every tile references events that exist in the project, every breakdown references a property that exists, date ranges are sensible, and the result is created via the MCP `dashboards-create-from-template-json-create` tool — not described in chat.

## When to use

The user is asking for a _new_ dashboard, expresses a topic, and is not referencing an existing dashboard. Common phrasings:

- "create a retention dashboard"
- "build me an acquisition dashboard for our new signup flow"
- "scaffold a feature-adoption dashboard for export"
- "set up a starter dashboard, I just instrumented PostHog"
- "show me a dashboard about how my product is doing"

## When NOT to use

- The user names an existing dashboard (by id, by name, by url). Use `dashboard-get`, `dashboard-update`, or `dashboard-reorder-tiles`.
- The user wants to summarise or explain dashboard _N_. Use `dashboard-get` plus `dashboard-insights-run`.
- The user is picking a static template manually in the new-dashboard modal.
- The user only wants a single insight saved. Use `insight-create`.
- The user asks for a one-off _report_ or _analysis_ (no dashboard intended).

## Workflow

### 1. Classify the archetype

Match the topic to one of:

| Archetype           | Match phrases                                                             | Reference                         |
| ------------------- | ------------------------------------------------------------------------- | --------------------------------- |
| `retention`         | retention, churn, sticky, do users come back                              | `references/retention.md`         |
| `acquisition`       | acquisition, signup, traffic, marketing, channel                          | `references/acquisition.md`       |
| `conversion-funnel` | funnel, conversion, drop-off, step                                        | `references/conversion-funnel.md` |
| `engagement`        | engagement, DAU, activity, usage, stickiness                              | `references/engagement.md`        |
| `feature-adoption`  | feature adoption, feature [name], rollout, tried, used                    | `references/feature-adoption.md`  |
| `revenue`           | revenue, MRR, ARR, ARPU, paid, monetisation                               | `references/revenue.md`           |
| `general`           | starter dashboard, just instrumented, overview, "how is my product doing" | `references/general.md`           |

If a topic spans two archetypes ("feature-adoption funnel"), pick the more specific one. If nothing matches, fall through to `general`. **Read the matching reference file via `llma-skill-file-get` before continuing** — it specifies the canonical tile set and any archetype-specific query shapes and fallback rules.

### 2a. Read top-event taxonomy

One `execute-sql` call:

```sql
SELECT event, count() AS c
FROM events
WHERE timestamp >= now() - INTERVAL 30 DAY
  AND event NOT IN ('$pageleave', '$autocapture', '$set', '$feature_flag_called', '$$heatmap')
GROUP BY event
ORDER BY c DESC
LIMIT 100
```

Cache the result for the rest of the run.

### 2b. Read properties for the events the archetype needs

After step 1 picked an archetype, its reference file names the 1–3 events whose properties matter (e.g. retention only needs the _key action_; conversion-funnel needs the _first funnel step_). Fan out one `read-data-schema` call per needed event **in parallel**:

```text
call read-data-schema {"query": {"kind": "event_properties", "event_name": "<event>"}}
```

Do not fetch properties for every top event — that wastes time. Defer property discovery until the archetype reference tells you which event(s) to probe.

### 3. Enrich the spec

Produce an internal plan before writing any JSON. Required shape:

```yaml
dashboard:
  name: "<3–6 words, title case>"
  description: "<one sentence describing the dashboard's purpose>"
  archetype: <one of: retention | acquisition | conversion-funnel | engagement | feature-adoption | revenue | general>
tiles:
  - intent: "<what this tile answers>"
    query_kind: <TrendsQuery | FunnelsQuery | RetentionQuery | LifecycleQuery | StickinessQuery | PathsQuery>
    events: [<event names from step 2a>]
    math: <dau | total | sum | unique_session | first_time_for_user | ...>
    breakdown: <property from step 2b, or null>
    date_range: <e.g. -30d, -90d, -7d>
    layout: <one of the layout vocabulary names — see below>
    rationale: "<one line — why this tile is in this dashboard>"
```

Ground every event/property reference in step 2's data. If you find yourself drafting a tile whose event wasn't in step 2a, stop. Pick a different event, ask the user (step 4), or escalate to the archetype's `## Fallback` section.

### 4. Confidence check + optional refine

**High confidence** when (a) one event obviously fits each role the archetype needs, and (b) every breakdown property exists on the events that use it.

**Low confidence** when two or more events plausibly fit the same role with similar volume, or a critical property is missing, or the topic is vague.

- High confidence → continue to step 5.
- Low confidence → ask **at most 2** multiple-choice questions, each presenting 2–4 named alternatives plus "none of these". Reserve questions for _event identity_ (which event is the signup?). Do not ask about breakdown property choice or date range — those fall through to the archetype's fallback. If still ambiguous after 2 answers, fall back per the archetype's `## Fallback` section.

Example question:

> Which event represents a completed signup? (a) `user_signed_up` (2,341 in 30d), (b) `signup_completed` (1,890 in 30d), (c) something else.

### 5. Generate tile queries

For each tile in the spec, emit the actual JSON. Reach for, in order:

1. A canonical template below — fastest path, no novel shape.
2. The archetype reference's archetype-specific template — for funnels, retention with non-default windows, formulas, breakdowns.
3. A custom shape only if neither of the above fits.

Pick `color` from the rotation `["blue", "green", "purple", "black"]` cycling per tile. Every tile must include `layouts` for both `sm` and `xs` breakpoints (see "Layout vocabulary" below).

### 6. Create the dashboard

Call `dashboards-create-from-template-json-create` once:

```json
{
  "template": {
    "template_name": "<dashboard name from step 3>",
    "dashboard_description": "<dashboard description from step 3>",
    "dashboard_filters": {},
    "tiles": [<the assembled tile array from step 5>]
  },
  "creation_context": "posthog-code-dashboards"
}
```

`creation_context` is a free-text analytics tag — `posthog-code-dashboards` lets the dashboards team attribute usage to this skill. The response includes the new dashboard `id`.

### 7. Return the URL

Report the result tersely:

```text
Created **{name}** with {N} tiles: {tile names, joined with commas, last with "and"}. View it at [/dashboard/{id}](/dashboard/{id}).
```

Do not dump the tile list, the raw JSON, or step-by-step reasoning.

## Canonical templates

These shapes are referenced by every archetype. Substitute `{KEY_EVENT}` (and any other `{PLACEHOLDER}`s) where used.

### Choosing the key event (used by retention, engagement, feature-adoption, general)

The highest-volume custom event from step 2a that is not in PostHog's noise list (`$pageleave`, `$autocapture`, `$set`, `$feature_flag_called`, `$$heatmap`) and has > 1,000 events in 30 days. If no custom event meets the bar, use `$pageview`. If `$pageview` has < 100 events, use `$autocapture`. If neither, abort and ask the user to instrument something to track.

Reference files override this default only when they need to.

### Tile JSON envelope

```json
{
  "name": "<title>",
  "type": "INSIGHT",
  "color": "<blue|green|purple|black>",
  "description": "<one sentence>",
  "query": { "kind": "InsightVizNode", "source": <query source below> },
  "layouts": <from layout vocabulary below>
}
```

### DAU on key event

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "{KEY_EVENT}", "name": "{KEY_EVENT}", "math": "dau" }],
  "interval": "day",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph" },
  "filterTestAccounts": false
}
```

### WAU on key event

`math: "weekly_active"` is the dedicated rolling-7-day-active math — distinct from `dau` bucketed weekly. Use this for WAU semantics, not `dau` with `interval: "week"`.

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "{KEY_EVENT}", "name": "{KEY_EVENT}", "math": "weekly_active" }],
  "interval": "day",
  "dateRange": { "date_from": "-90d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph" },
  "filterTestAccounts": false
}
```

### MAU on key event

Same as WAU, but `math: "monthly_active"` and `date_from: "-180d"`.

### Weekly retention on key event

```json
{
  "kind": "RetentionQuery",
  "dateRange": { "date_from": "-77d", "explicitDate": false },
  "retentionFilter": {
    "period": "Week",
    "totalIntervals": 11,
    "retentionType": "retention_first_time",
    "targetEntity": { "id": "{KEY_EVENT}", "type": "events" },
    "returningEntity": { "id": "{KEY_EVENT}", "type": "events" }
  },
  "filterTestAccounts": false
}
```

### Lifecycle on key event

```json
{
  "kind": "LifecycleQuery",
  "series": [{ "kind": "EventsNode", "event": "{KEY_EVENT}", "name": "{KEY_EVENT}" }],
  "interval": "week",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "lifecycleFilter": { "showLegend": false },
  "filterTestAccounts": false
}
```

### Stickiness on key event

```json
{
  "kind": "StickinessQuery",
  "series": [{ "kind": "EventsNode", "event": "{KEY_EVENT}", "name": "{KEY_EVENT}" }],
  "interval": "week",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "stickinessFilter": {},
  "filterTestAccounts": false
}
```

### Top events ranking

`event: null` plus an `event_metadata` breakdown ranks every event in the period by volume.

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": null, "name": "All events", "math": "total" }],
  "interval": "day",
  "dateRange": { "date_from": "-7d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsBarValue" },
  "breakdownFilter": { "breakdown_type": "event_metadata", "breakdown": "event", "breakdown_limit": 15 },
  "filterTestAccounts": false
}
```

## Layout vocabulary

The grid is 12 columns wide on `sm` and 1 column on `xs`. Use these named patterns rather than re-deriving coordinates per archetype. Increment `y` by 5 for each row consumed; on `xs`, stack everything at `w: 1` with `y` incrementing by 5 per tile in declared order. Every tile uses `minH: 5, minW: 3`.

| Name            | `sm` placement                          | Use when                      |
| --------------- | --------------------------------------- | ----------------------------- |
| `full`          | `w: 12, x: 0` — fills the row           | Anchor tile or summary chart  |
| `pair-left`     | `w: 6, x: 0` — left half of a 2-up row  | First of two tiles on a row   |
| `pair-right`    | `w: 6, x: 6` — right half of a 2-up row | Second of two tiles on a row  |
| `triple-left`   | `w: 4, x: 0`                            | First of three tiles on a row |
| `triple-middle` | `w: 4, x: 4`                            | Second of three               |
| `triple-right`  | `w: 4, x: 8`                            | Third of three                |

Archetype reference files name the pattern per tile, e.g. _"5 tiles: `full`, `pair-left`, `pair-right`, `pair-left`, `pair-right`"_. Compute the actual `y` and `xs.y` from the order.

Example — a `pair-left` tile that is the 3rd tile on a dashboard (so on the 2nd row, since tile 1 was `full` and consumed the 1st row):

```json
"layouts": {
  "sm": {"w": 6, "h": 5, "x": 0, "y": 5, "minH": 5, "minW": 3},
  "xs": {"w": 1, "h": 5, "x": 0, "y": 10, "minH": 5, "minW": 3}
}
```

## Failure modes to avoid

- **Generating before step 2a.** Always read top-event taxonomy first; otherwise tiles will reference events that don't exist.
- **Asking more than 2 refine questions.** If still ambiguous after 2 answers, fall back per the archetype's `## Fallback` section — never round-trip the user a third time.
- **Inventing breakdown properties.** Only break down by properties confirmed via step 2b. If the archetype reference asks for a breakdown that doesn't exist, drop that tile per the archetype's fallback rules.
- **Using `dashboard-create` for this skill.** That tool creates an empty dashboard and forces N follow-up `insight-create` + tile-attach calls. The `dashboards-create-from-template-json-create` path used in step 6 creates everything in one round-trip — always prefer it here.
- **Returning the JSON in chat.** Step 6 creates the dashboard; step 7 returns the URL. The user never sees the tile JSON unless they explicitly ask.
- **Silent fallback when the user named a specific archetype.** If the user said "retention dashboard" but the data forces a fallback to `general`, _say so_ — let the user accept it or give more context.

## See also

- `posthog:querying-posthog-data` — HogQL syntax constraints for step 2a.
- `posthog:exploring-autocapture-events` — when `$autocapture`/`$pageview` are usable fallbacks.
- `posthog:formatting-insight-axes` — picking `aggregationAxisFormat` for revenue, ARPU, duration tiles.
- `references/<archetype>.md` — required reading once step 1 picks an archetype.
