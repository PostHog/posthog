# Retention archetype

## Purpose

Answer: do users come back? Combine one cohort-level retention chart, one lifecycle chart, and headline DAU/WAU on the recurring key action.

## Properties needed (step 2b input)

Probe properties for the chosen key event only — no other events.

## Canonical tile set (5 tiles)

| #   | Tile                           | Source                                     | Layout       |
| --- | ------------------------------ | ------------------------------------------ | ------------ |
| 1   | Weekly retention on key action | SKILL.md → "Weekly retention on key event" | `full`       |
| 2   | Lifecycle                      | SKILL.md → "Lifecycle on key event"        | `pair-left`  |
| 3   | Stickiness                     | SKILL.md → "Stickiness on key event"       | `pair-right` |
| 4   | DAU                            | SKILL.md → "DAU on key event"              | `pair-left`  |
| 5   | WAU                            | SKILL.md → "WAU on key event"              | `pair-right` |

Substitute `{KEY_EVENT}` everywhere with the event chosen via SKILL.md's "Choosing the key event" rule.

## Archetype-specific guidance

- The retention tile is the dashboard anchor — give it the `full` row.
- Use the default 11 weekly intervals from the canonical template; don't shorten it.

## Fallback

If no custom event meets the > 1,000 events / 30d bar, key event becomes `$pageview` and the dashboard name becomes "Pageview retention" so the user sees what's being measured.
