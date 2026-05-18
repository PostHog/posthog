# Engagement archetype

## Purpose

Answer: how active are users overall? Headline DAU/WAU/MAU, sessions per user, stickiness on the key action, and a top-events ranking so the user can see which events drive engagement.

## Properties needed (step 2b input)

None — engagement uses no event-specific breakdowns.

## Canonical tile set (6 tiles)

| #   | Tile                       | Source                               | Layout          |
| --- | -------------------------- | ------------------------------------ | --------------- |
| 1   | DAU                        | SKILL.md → "DAU on key event"        | `triple-left`   |
| 2   | WAU                        | SKILL.md → "WAU on key event"        | `triple-middle` |
| 3   | MAU                        | SKILL.md → "MAU on key event"        | `triple-right`  |
| 4   | Sessions per user (weekly) | Template below                       | `pair-left`     |
| 5   | Stickiness                 | SKILL.md → "Stickiness on key event" | `pair-right`    |
| 6   | Top events                 | SKILL.md → "Top events ranking"      | `full`          |

`{KEY_EVENT}` is chosen via SKILL.md's "Choosing the key event" rule.

## Archetype-specific templates

### Tile 4 — Sessions per user (formula)

Uses a 2-series formula. A is unique sessions, B is DAU; the formula gives sessions-per-user.

```json
{
  "kind": "TrendsQuery",
  "series": [
    { "kind": "EventsNode", "event": "$pageview", "name": "Sessions", "math": "unique_session" },
    { "kind": "EventsNode", "event": "$pageview", "name": "Users", "math": "dau" }
  ],
  "interval": "week",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph", "formula": "A/B" },
  "filterTestAccounts": false
}
```

## Fallback

- No `$pageview` for the sessions/user formula → drop tile 4 and expand tile 5 to `full`.
- No custom events meet the bar → key event becomes `$pageview` and the dashboard name becomes "Pageview engagement".
