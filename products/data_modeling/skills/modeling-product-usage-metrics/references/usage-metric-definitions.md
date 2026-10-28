# Product-usage metric definitions

All three lenses share: a chosen **event/action**, an **interval** (day/week/month), and an **aggregation
unit** (person or group).

## Retention

For a cohort defined by the interval of their **start event** (often first-ever occurrence), the share who
performed the **return event** in each subsequent interval.

- Output: a matrix — rows = entry interval, columns = "N intervals later", cells = retained count / %.
- **Recurring** retention: active _in_ interval N (independent per interval). The common default.
- **Cumulative / "rolling"** variant: active in N and every interval up to N.
- Start event and return event can differ (e.g. `signed_up` → `ran_query`).

## Stickiness

For the chosen event over a fixed span (e.g. last 7 days / 4 weeks), bucket each unit by **how many distinct
intervals** they were active, then count units per bucket.

- Output: distribution — x = number of active intervals, y = number of units.
- Surfaces power users (high-interval buckets) and feature stickiness.
- The DAU/WAU or DAU/MAU ratio is a scalar summary of the same idea.

## Lifecycle

Classify each unit's activity in each interval relative to the previous interval and the interval in which the
unit started:

| Bucket           | Meaning                                                                        |
| ---------------- | ------------------------------------------------------------------------------ |
| **New**          | Active this interval, and the unit started this interval.                      |
| **Returning**    | Active this interval and the immediately previous interval (not new).          |
| **Resurrecting** | Active this interval, inactive the previous interval, and not new.             |
| **Dormant**      | Not active this interval, but active the previous interval (plotted negative). |

- **When a unit started depends on the platform.**
  - PostHog (`query-lifecycle` and the HogQL recipe): the person profile `created_at`.
  - dbt or another warehouse: the first-ever chosen event over the full event history, or `created_at` from a
    users table if you have one.
- On PostHog, a person created in an earlier interval than their first chosen event counts as resurrecting in
  that interval, not new.
- Do not use "first event inside the analysis window" as new. It labels every existing user who is active at
  the window's start as new. Use the full history or a profile creation date.
- Output: stacked bars per interval (dormant negative). New + returning + resurrecting = active users;
  dormant shows churn out.
- Reading: dormant outpacing returning + resurrecting = leaky bucket (growth masks churn); resurrection
  spikes = win-back working; returning plateau = engagement ceiling.
