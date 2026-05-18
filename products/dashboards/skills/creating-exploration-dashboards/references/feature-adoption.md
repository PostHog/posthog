# Feature adoption archetype

## Purpose

Answer: who is using this feature and are they sticking with it? The user names a feature (often by its event name); the dashboard tracks who tried it, who repeats, and whether adopters retain better than non-adopters.

## Properties needed (step 2b input)

Properties of the chosen feature event — used to pick a breakdown for tile 3.

## Choosing the events

- **Feature event** (`{FEATURE_EVENT}`): the user typically names this. Find the highest-volume event whose name contains the feature word (e.g. user says "export" → look for `export_*`, `exported_*`, `*_export`). If multiple plausible matches, ask via SKILL.md step 4.
- **"Saw" event** (`{SAW_EVENT}`): an event indicating the user encountered the feature without engaging. Common shapes: `{feature}_button_viewed`, `{feature}_modal_shown`, or `$pageview` on the feature's page. If none, drop the first step of tile 2.
- **"Tried" event** (`{TRIED_EVENT}`): the feature event itself, or a `{feature}_started` precursor if present.

## Choosing the breakdown property

Prefer custom properties on the feature event (`format`, `plan_type`, `team_size`); fall back to `$browser` or `$os`. Skip tile 3 if no property has > 2 distinct values.

## Canonical tile set (5 tiles)

| #   | Tile                     | Source                                                                                                    | Layout       |
| --- | ------------------------ | --------------------------------------------------------------------------------------------------------- | ------------ |
| 1   | Users over time          | SKILL.md → "DAU on key event" with `{KEY_EVENT} = {FEATURE_EVENT}`                                        | `pair-left`  |
| 2   | Adoption funnel          | Template below                                                                                            | `pair-right` |
| 3   | Usage by breakdown       | Template below                                                                                            | `pair-left`  |
| 4   | Repeat usage (retention) | SKILL.md → "Weekly retention on key event" with `{KEY_EVENT} = {FEATURE_EVENT}` (8 intervals — see below) | `pair-right` |
| 5   | Adoption rate over time  | Template below                                                                                            | `full`       |

## Archetype-specific templates

### Tile 2 — Adoption funnel

Funnel steps do not accept a per-step `math`; "used again" is naturally captured by the funnel running an event sequence that ends in a second occurrence of `{FEATURE_EVENT}` after `{TRIED_EVENT}`. If `{TRIED_EVENT}` and `{FEATURE_EVENT}` are the same event, drop step 2 and use a 2-step funnel instead.

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "{SAW_EVENT}", "name": "Saw" },
    { "kind": "EventsNode", "event": "{TRIED_EVENT}", "name": "Tried" },
    { "kind": "EventsNode", "event": "{FEATURE_EVENT}", "name": "Used again" }
  ],
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "funnelsFilter": { "funnelVizType": "steps", "funnelWindowInterval": 14, "funnelWindowIntervalUnit": "day" },
  "filterTestAccounts": false
}
```

### Tile 3 — Breakdown

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "{FEATURE_EVENT}", "name": "{FEATURE_EVENT}", "math": "total" }],
  "interval": "day",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsBarValue" },
  "breakdownFilter": { "breakdown_type": "event", "breakdown": "{BREAKDOWN_PROPERTY}", "breakdown_limit": 5 },
  "filterTestAccounts": false
}
```

### Tile 4 — Repeat usage override

Use the canonical "Weekly retention on key event" shape but adjust `totalIntervals: 8` and `date_from: "-56d"` for a feature-launch-friendly 8-week view.

### Tile 5 — Adoption rate (formula)

A is adopters of the feature, B is all active users. Formula `A/B` rendered as a percentage.

```json
{
  "kind": "TrendsQuery",
  "series": [
    { "kind": "EventsNode", "event": "{FEATURE_EVENT}", "name": "Adopters", "math": "dau" },
    { "kind": "EventsNode", "event": null, "name": "Active users", "math": "dau" }
  ],
  "interval": "week",
  "dateRange": { "date_from": "-90d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph", "formula": "A/B", "aggregationAxisFormat": "percentage" },
  "filterTestAccounts": false
}
```

## Fallback

- No "saw" event → tile 2 becomes a 2-step funnel (tried → used again).
- No breakdown property → drop tile 3 and expand tile 4 to `full`.
- Feature event has < 50 unique users in 30 days → still build, but note in the dashboard description that adoption is below the reliable-stats threshold.
