# Conversion funnel archetype

## Purpose

Answer: where do users drop off in a specific sequence? Centre the dashboard on one funnel and surround it with cuts that explain the drop-off.

## Properties needed (step 2b input)

Properties of the funnel's _first_ event only — used to pick a breakdown for tile 3.

## Choosing the funnel steps

- The user usually names the steps explicitly ("signup → onboarding → first action"). Map each name to an event from step 2a.
- If a name is ambiguous (two candidate events for the same step), ask via SKILL.md step 4 — questions are reserved for event identity, this is allowed.
- A funnel needs at least 2 events. If the user only named one, reclassify as `engagement` — do not produce a 1-step funnel.

## Choosing the breakdown property (tile 3)

In order of preference:

1. A custom plan/segment property if it exists (`plan_type`, `customer_tier`, `is_paying`).
2. `$geoip_country_code` for global products.
3. `$browser` or `$os` for products with diverse client surfaces.

Skip tile 3 entirely if no candidate property has > 2 distinct values across the funnel's first event.

## Canonical tile set (4 tiles)

| #   | Tile                 | Source         | Layout       |
| --- | -------------------- | -------------- | ------------ |
| 1   | Main funnel (steps)  | Template below | `full`       |
| 2   | Conversion over time | Template below | `pair-left`  |
| 3   | By breakdown         | Template below | `pair-right` |
| 4   | Time to convert      | Template below | `full`       |

## Archetype-specific templates

Substitute `{STEP_1}`, `{STEP_2}`, `{STEP_3}`, `{BREAKDOWN_PROPERTY}`. For funnels with 2 or 4–5 steps, adjust the `series` array length.

### Tile 1 — Funnel steps

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "{STEP_1}", "name": "{STEP_1}" },
    { "kind": "EventsNode", "event": "{STEP_2}", "name": "{STEP_2}" },
    { "kind": "EventsNode", "event": "{STEP_3}", "name": "{STEP_3}" }
  ],
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "funnelsFilter": {
    "funnelVizType": "steps",
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day",
    "funnelOrderType": "ordered"
  },
  "filterTestAccounts": false
}
```

### Tile 2 — Funnel trends

Same `series` as tile 1, plus:

```json
"funnelsFilter": {
  "funnelVizType": "trends",
  "funnelWindowInterval": 14,
  "funnelWindowIntervalUnit": "day",
  "funnelOrderType": "ordered"
},
"interval": "day"
```

### Tile 3 — Funnel with breakdown

Same `series` and `funnelsFilter` as tile 1, plus:

```json
"breakdownFilter": {"breakdown_type": "event", "breakdown": "{BREAKDOWN_PROPERTY}"}
```

`FunnelsFilter` does not accept a `breakdown_limit` field — the default cap is applied automatically.

### Tile 4 — Time to convert

Same `series` as tile 1, plus:

```json
"funnelsFilter": {
  "funnelVizType": "time_to_convert",
  "funnelWindowInterval": 14,
  "funnelWindowIntervalUnit": "day",
  "funnelOrderType": "ordered"
}
```

## Fallback

- The user named only one event → reclassify as `engagement` (handled by SKILL.md step 4's fallback rule).
- End-to-end conversion is < 1% → still build; extend the window to 30 days and note in the dashboard description that the funnel runs at low volume.
- Breakdown property has only 1 distinct value → drop tile 3 and expand tile 2 to `full`.
