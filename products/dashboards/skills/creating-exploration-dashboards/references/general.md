# General archetype (starter dashboard)

## Purpose

The catch-all. Use when:

- The user's topic doesn't match a specific archetype.
- The project has too few custom events for a targeted archetype to be meaningful (the > 1,000 events / 30d bar from SKILL.md).
- The user explicitly wants a "starter" / "overview" / "just installed PostHog" dashboard.

The shape mirrors PostHog's built-in "Product analytics" template but generated against the project's actual top event instead of always defaulting to `$pageview`.

## Properties needed (step 2b input)

Properties of `$pageview` only (to confirm `$referring_domain` exists for tile 6). Skip property fetching entirely if there is no `$pageview`.

## Canonical tile set (5–6 tiles)

`{TOP_EVENT}` is the chosen key event per SKILL.md's "Choosing the key event" rule.

| #   | Tile             | Source                                                         | Layout       |
| --- | ---------------- | -------------------------------------------------------------- | ------------ |
| 1   | DAU              | SKILL.md → "DAU on key event" with `{KEY_EVENT} = {TOP_EVENT}` | `pair-left`  |
| 2   | WAU              | SKILL.md → "WAU on key event"                                  | `pair-right` |
| 3   | Retention        | SKILL.md → "Weekly retention on key event"                     | `pair-left`  |
| 4   | Lifecycle        | SKILL.md → "Lifecycle on key event"                            | `pair-right` |
| 5   | Top events       | SKILL.md → "Top events ranking"                                | `full`       |
| 6   | Referring domain | Template below — **only include if `$pageview` exists**        | `full`       |

## Archetype-specific template

### Tile 6 — Referring domain (only if `$pageview` exists)

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "name": "$pageview", "math": "dau" }],
  "interval": "day",
  "dateRange": { "date_from": "-14d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsBarValue" },
  "breakdownFilter": { "breakdown_type": "event", "breakdown": "$referring_domain" },
  "filterTestAccounts": false
}
```

## Fallback

- No `$pageview` → ship 5 tiles (skip tile 6).
- Project has < 100 events total → abort. Tell the user there's no data yet and offer to walk them through setting up the PostHog SDK.
