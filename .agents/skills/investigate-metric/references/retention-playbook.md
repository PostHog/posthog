# Retention metrics playbook

For "week-1 retention regressed", "March cohort isn't coming back",
"cohort X's week-N retention fell".

Steps reference [shared-patterns.md](./shared-patterns.md) for reusable recipes.

## 1. Isolate the affected cohort

`posthog:query-retention` broken out by start cohort. Compare the affected cohort(s) to
baseline cohorts side by side.

`targetEntity` / `returningEntity` use `{type: "events", name: "<event>"}` (or
`{type: "actions", id: <id>, name: "..."}`). They are nested inside `retentionFilter`.

```json
{
  "kind": "RetentionQuery",
  "dateRange": { "date_from": "-90d" },
  "retentionFilter": {
    "targetEntity": { "type": "events", "name": "$pageview" },
    "returningEntity": { "type": "events", "name": "$pageview" },
    "totalIntervals": 8,
    "period": "Week",
    "retentionType": "retention_first_time"
  }
}
```

## 2. Scope to the retained-activity event

Is the drop in the event itself, or in the users doing it? Create (or reuse) a cohort for
the affected start period via `posthog:cohorts-create` / `posthog:cohorts-list`, then run
a trends query on the retained-activity event filtered to that cohort:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "series": [{ "kind": "EventsNode", "event": "core_action", "math": "dau" }],
  "properties": [{ "type": "cohort", "key": "id", "value": 42, "operator": "in" }]
}
```

Apply the **breakdown dimensions** menu from shared-patterns to this trend if you want to
see which slice of the affected cohort isn't coming back.

## 3. Split the dropout

`posthog:query-lifecycle` scoped to the affected cohort — separate new users who never
returned after week 0 from returning users who churned later in the period:

```json
{
  "kind": "LifecycleQuery",
  "dateRange": { "date_from": "-30d" },
  "interval": "week",
  "series": [
    {
      "kind": "EventsNode",
      "event": "core_action",
      "properties": [{ "type": "cohort", "key": "id", "value": 42, "operator": "in" }]
    }
  ]
}
```

This distinguishes "we never retained them in the first place" from "we retained them
initially then lost them later" — different root causes, different follow-ups.
