# Acquisition archetype

## Purpose

Answer: where do users come from and how many convert? Combine top-of-funnel counts with channel breakdowns and a signup funnel.

## Properties needed (step 2b input)

- Properties of `$pageview` (specifically the presence of `$referring_domain`, `utm_source`, `utm_medium`).
- Properties of the chosen signup event (to confirm the funnel can use it).

## Choosing the signup and activation events

- **Signup event** (`{SIGNUP_EVENT}`): highest-volume event whose name matches `signed_up`, `user_signed_up`, `signup_completed`, `account_created`. If multiple plausible candidates, ask via SKILL.md step 4.
- **Activation event** (`{ACTIVATION_EVENT}`): the next most-common post-signup event. Common patterns: `email_verified`, `onboarding_completed`, or the key event from the engagement archetype.

If no signup-shaped event exists, drop tiles 4 and 5 entirely — do **not** substitute `$identify` (it fires on every login/init, not just first signup, and would produce misleading channel charts).

## Canonical tile set (5 tiles)

| #   | Tile                              | Source                                                                           | Layout       |
| --- | --------------------------------- | -------------------------------------------------------------------------------- | ------------ |
| 1   | New users over time               | Template below — `math: first_time_for_user` (true first-time visitors, not DAU) | `pair-left`  |
| 2   | Traffic by referring domain (14d) | Template below                                                                   | `pair-right` |
| 3   | UTM source breakdown (30d)        | Template below                                                                   | `pair-left`  |
| 4   | Signup funnel                     | Template below                                                                   | `pair-right` |
| 5   | Signups by channel                | Template below                                                                   | `full`       |

## Archetype-specific templates

Substitute `{SIGNUP_EVENT}`, `{ACTIVATION_EVENT}`.

### Tile 1 — New users over time

`math: first_time_for_user` counts each user only on their first occurrence of the event — true acquisition semantics, not "daily active users".

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "$pageview", "name": "New users", "math": "first_time_for_user" }],
  "interval": "day",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph" },
  "filterTestAccounts": false
}
```

### Tile 2 — Referring domain (14d, bar)

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

### Tile 3 — UTM source (30d, bar)

Same as tile 2 with `"breakdown": "utm_source"` and `"date_from": "-30d"`.

### Tile 4 — Signup funnel

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "$pageview", "name": "Landing" },
    { "kind": "EventsNode", "event": "{SIGNUP_EVENT}", "name": "Signed up" },
    { "kind": "EventsNode", "event": "{ACTIVATION_EVENT}", "name": "Activated" }
  ],
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "funnelsFilter": { "funnelVizType": "steps", "funnelWindowInterval": 14, "funnelWindowIntervalUnit": "day" },
  "filterTestAccounts": false
}
```

### Tile 5 — Signups by channel

`math: total` (not `dau`) because the chart counts signup events per channel, not unique-users-per-channel.

```json
{
  "kind": "TrendsQuery",
  "series": [{ "kind": "EventsNode", "event": "{SIGNUP_EVENT}", "name": "Signups", "math": "total" }],
  "interval": "day",
  "dateRange": { "date_from": "-30d", "explicitDate": false },
  "trendsFilter": { "display": "ActionsLineGraph" },
  "breakdownFilter": { "breakdown_type": "event", "breakdown": "$referring_domain" },
  "filterTestAccounts": false
}
```

## Fallback

- No `utm_source` on `$pageview` → drop tile 3, expand tile 5 to `full`.
- No signup-shaped event → drop tiles 4 and 5; rename the dashboard "Traffic overview" so the user sees the smaller scope.
