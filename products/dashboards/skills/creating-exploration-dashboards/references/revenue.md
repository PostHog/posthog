# Revenue archetype

## Purpose

Answer: how much money is being made, by whom, and is it growing? Revenue only works when the project actually captures revenue data — events with amount properties or warehouse-backed revenue tables.

## Pre-check (mandatory)

Before producing any tile, confirm at least one of the following exists in step 2a's taxonomy:

1. An event with a numeric "amount" / "revenue" / "total" / "price" property (verify via `read-data-schema` `event_properties`).
2. A Stripe/payments-shaped event: `payment_completed`, `subscription_created`, `invoice_paid`, `charge_succeeded`.
3. A data-warehouse table the user references explicitly.

**If none exist, abort this archetype.** Tell the user: _"I couldn't find revenue events or properties in your project — connect Stripe via the data warehouse or send revenue events with an amount property, then try again."_ Do not silently fall back to `general` — the user explicitly asked for revenue.

## Properties needed (step 2b input)

Properties of the chosen revenue event — to confirm the amount property exists and to pick a plan/segment breakdown if available.

## Choosing the events

- **Revenue event** (`{REVENUE_EVENT}`): highest-volume event with a numeric amount property. Common names: `payment_completed`, `subscription_charged`, `order_placed`, `invoice_paid`.
- **Amount property** (`{AMOUNT_PROPERTY}`): numeric property on the revenue event. Use `read-data-schema` `event_property_values` to confirm it parses as a number.
- **Plan/segment property** (`{PLAN_PROPERTY}`): plan name, tier, or subscription type. If none, drop tile 2.
- **Signup event** (`{SIGNUP_EVENT}`): from the acquisition archetype's rules. If none, drop tile 5.

If revenue is denominated in multiple currencies, prefer a property normalised to one (`amount_usd`, `total_in_cents`). If none, note it in the dashboard description.

## Canonical tile set (5 tiles)

| #   | Tile                 | Source         | Layout       |
| --- | -------------------- | -------------- | ------------ |
| 1   | Revenue over time    | Template below | `pair-left`  |
| 2   | Revenue by plan      | Template below | `pair-right` |
| 3   | Paying users         | Template below | `pair-left`  |
| 4   | ARPU                 | Template below | `pair-right` |
| 5   | Signup → Paid funnel | Template below | `full`       |

## Archetype-specific templates

Substitute `{REVENUE_EVENT}`, `{AMOUNT_PROPERTY}`, `{PLAN_PROPERTY}`, `{SIGNUP_EVENT}`.

### Tile 1 — Revenue over time

Set `aggregationAxisFormat` to match the amount unit; see `posthog:formatting-insight-axes`.

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "{REVENUE_EVENT}",
      "name": "Revenue",
      "math": "sum",
      "math_property": "{AMOUNT_PROPERTY}"
    }
  ],
  "interval": "day",
  "dateRange": { "date_from": "-90d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph", "aggregationAxisFormat": "numeric" },
  "filterTestAccounts": false
}
```

### Tile 2 — Revenue by plan

Tile 1 plus:

```json
"breakdownFilter": {"breakdown_type": "event", "breakdown": "{PLAN_PROPERTY}", "breakdown_limit": 5}
```

### Tile 3 — Paying users

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "{REVENUE_EVENT}", "name": "Payers", "math": "dau" }],
  "interval": "week",
  "dateRange": { "date_from": "-90d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph" },
  "filterTestAccounts": false
}
```

### Tile 4 — ARPU (formula)

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "{REVENUE_EVENT}",
      "name": "Revenue",
      "math": "sum",
      "math_property": "{AMOUNT_PROPERTY}"
    },
    { "kind": "EventsNode", "event": "{REVENUE_EVENT}", "name": "Payers", "math": "dau" }
  ],
  "interval": "week",
  "dateRange": { "date_from": "-90d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph", "formula": "A/B", "aggregationAxisFormat": "numeric" },
  "filterTestAccounts": false
}
```

### Tile 5 — Signup → first payment funnel

Uses a 30-day funnel window (longer than the 14-day default) because conversion to paid is typically slower than product funnels.

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "{SIGNUP_EVENT}", "name": "Signed up" },
    { "kind": "EventsNode", "event": "{REVENUE_EVENT}", "name": "First payment", "math": "first_time_for_user" }
  ],
  "dateRange": { "date_from": "-90d", "explicitDate": false },
  "funnelsFilter": { "funnelVizType": "steps", "funnelWindowInterval": 30, "funnelWindowIntervalUnit": "day" },
  "filterTestAccounts": false
}
```

## Fallback (within the archetype — do not fall back to `general`)

- No `{PLAN_PROPERTY}` → drop tile 2; tile 1 becomes `full`.
- No `{SIGNUP_EVENT}` → drop tile 5; tile 4 becomes `full`.
- Revenue data is warehouse-only (no event) → tell the user the dashboard would need warehouse-backed insights (`HogQLQuery` against the warehouse table) and offer to build that variant instead of generating a broken dashboard.
