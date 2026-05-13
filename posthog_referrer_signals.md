# PostHog Referral Candidate Identifier — Agent Skill

## Purpose

This skill identifies PostHog users who are highly primed to refer PostHog to others. The agent searches PostHog behavioural data for individuals matching a set of validated referral signals, then enriches each match with org name, billing MRR, and paid products to prioritise outreach.

---

## Step-by-Step Execution Plan

1. **Run the cross-reference query** — find all users who match 2+ signals (or filter to 4 for top-tier candidates)
2. **Collect `distinct_id` values** from the results
3. **Look up person details** — email, country, `organization_id`
4. **Look up org names** — via `$groupidentify` events using `properties.$group_0`
5. **Look up billing data** — forecasted MRR and paid plans per org
6. **Compile and present** the final table

---

## Signals

### Signal 1 — Login Streak (30+ weekdays in 60 days)

A user who logs in every working day for 30+ days is deeply embedded in their workflow. Weekends excluded using `toDayOfWeek(timestamp) NOT IN (6, 7)`.

**Threshold:** ≥30 distinct weekday dates with a `$pageview` event in the past 60 days.

### Signal 2 — Invited Colleagues

Inviting teammates is a strong proxy for advocacy — they already recommend PostHog within their org.

**Events to match:** `user invited`, `team member invited`, `bulk invite executed`  
**Threshold:** ≥1 invite event in the past 90 days.

### Signal 3 — Product Breadth (3+ product areas in 30 days)

Power users who span multiple PostHog products are more likely to talk about the platform holistically.

**Product areas detected via `$pathname`:**

- `analytics` — `/insights`, `/dashboard`
- `session_replay` — `/replay`, `/recordings`
- `feature_flags` — `/feature_flags`
- `surveys` — `/surveys`
- `experiments` — `/experiments`
- `data_warehouse` — `/data-warehouse`

**Threshold:** ≥3 distinct product areas visited in past 30 days.

### Signal 4 — NPS Promoter (score 9–10)

Self-reported promoters from PostHog's in-app NPS survey.

**Event:** `survey sent`  
**Filter:** `toInt(properties.$survey_response) >= 9 AND toInt(properties.$survey_response) <= 10`  
**Threshold:** ≥1 qualifying response in the past 180 days.

> ⚠️ **Important:** Always add the upper bound `<= 10` — test/bogus submissions like `10000000` exist in the data and must be excluded.

---

## Signal Amplifiers (not counted in signal score, used for prioritisation)

- **High-spend org** — `forecasted_mrr > 500` from `billing log` events
- **Large org** — visible from team member counts or org-level metadata

Use these to rank candidates after the signal query, not to gate inclusion.

---

## Matching Rules

| Signal Count | Label       | Action                |
| ------------ | ----------- | --------------------- |
| 4            | 🔥 Top-tier | Priority outreach     |
| 3            | ⭐ Strong   | High priority         |
| 2            | 👍 Good     | Consider for outreach |
| 1            | —           | Skip                  |

---

## Validated Cross-Reference Query

This query has been tested against live PostHog data. Run it as-is.

```sql
WITH
streak_users AS (
    SELECT distinct_id, 'login_streak' as signal
    FROM events
    WHERE event = '$pageview'
      AND timestamp >= now() - INTERVAL 60 DAY
      AND toDayOfWeek(timestamp) NOT IN (6, 7)
    GROUP BY distinct_id
    HAVING COUNT(DISTINCT toDate(timestamp)) >= 30
),
invite_users AS (
    SELECT distinct_id, 'invited_colleagues' as signal
    FROM events
    WHERE event IN ('user invited', 'team member invited', 'bulk invite executed')
      AND timestamp >= now() - INTERVAL 90 DAY
    GROUP BY distinct_id
    HAVING COUNT(*) >= 1
),
breadth_users AS (
    SELECT distinct_id, 'product_breadth' as signal
    FROM events
    WHERE event = '$pageview'
      AND timestamp >= now() - INTERVAL 30 DAY
    GROUP BY distinct_id
    HAVING COUNT(DISTINCT multiIf(
        properties.$pathname LIKE '%/insights%' OR properties.$pathname LIKE '%/dashboard%', 'analytics',
        properties.$pathname LIKE '%/replay%' OR properties.$pathname LIKE '%/recordings%', 'session_replay',
        properties.$pathname LIKE '%/feature_flags%', 'feature_flags',
        properties.$pathname LIKE '%/surveys%', 'surveys',
        properties.$pathname LIKE '%/experiments%', 'experiments',
        properties.$pathname LIKE '%/data-warehouse%', 'data_warehouse',
        NULL
    )) >= 3
),
nps_users AS (
    SELECT distinct_id, 'nps_promoter' as signal
    FROM events
    WHERE event = 'survey sent'
      AND toInt(properties.$survey_response) >= 9
      AND toInt(properties.$survey_response) <= 10
      AND timestamp >= now() - INTERVAL 180 DAY
    GROUP BY distinct_id
),
all_signals AS (
    SELECT * FROM streak_users
    UNION ALL SELECT * FROM invite_users
    UNION ALL SELECT * FROM breadth_users
    UNION ALL SELECT * FROM nps_users
)
SELECT
    distinct_id,
    COUNT(DISTINCT signal) as signal_count,
    groupArray(signal) as signals_matched
FROM all_signals
GROUP BY distinct_id
HAVING signal_count >= 2
ORDER BY signal_count DESC
LIMIT 100
```

To filter for top-tier only, change `HAVING signal_count >= 2` to `HAVING signal_count = 4`.

---

## Person Detail Lookup

After collecting `distinct_id` values (run for ≤20 at a time to avoid memory limits):

```sql
SELECT
    distinct_id,
    person.properties.email as email,
    person.properties.name as name,
    person.properties.$geoip_country_name as country,
    person.properties.organization_id as org_id
FROM events
WHERE distinct_id IN ('id1', 'id2', ...)
GROUP BY distinct_id, email, name, country, org_id
LIMIT 50
```

> Note: A single `distinct_id` may appear multiple times with different geoip values (VPN/travel). Pick the most recent or most common.

---

## Org Name Lookup

Use `$groupidentify` events with `properties.$group_0` (not `$group_set.organization_id`) to reliably match org IDs:

```sql
SELECT
    properties.$group_0 as org_id,
    argMax(JSONExtractString(properties.$group_set, 'name'), timestamp) as org_name
FROM events
WHERE event = '$groupidentify'
  AND properties.$group_type = 'organization'
  AND properties.$group_0 IN ('org_id_1', 'org_id_2', ...)
GROUP BY org_id
LIMIT 50
```

> ⚠️ Do NOT use `JSONExtractString(properties.$group_set, 'organization_id')` for the GROUP BY key — it returns blank. Use `properties.$group_0` instead.

---

## Billing Data Lookup

```sql
SELECT
    properties.organization_id as org_id,
    argMax(properties.forecasted_mrr, timestamp) as forecasted_mrr,
    argMax(properties.plans, timestamp) as plans
FROM events
WHERE event = 'billing log'
  AND properties.log_type = 'upcoming invoice forecasted mrr'
  AND properties.organization_id IN ('org_id_1', 'org_id_2', ...)
GROUP BY org_id
LIMIT 50
```

- `forecasted_mrr` is a numeric USD value (e.g. `1469.65`)
- `plans` is a JSON object — keys are product slugs (e.g. `product_analytics`, `feature_flags`, `data_warehouse`, `session_replay`, `surveys`, `experiments`, `error_tracking`, `llm_analytics`, `logs`)
- A value like `paid-20240404` means the org is on a paid plan for that product; `free` means free tier

---

## Output Format

Present results as a table with these columns:

| User (email) | Org Name | Country | Signals Matched | Forecasted MRR | Paid Products |
| ------------ | -------- | ------- | --------------- | -------------- | ------------- |

Sort by signal count descending, then MRR descending. Flag the top candidates clearly.

---

## HogQL Syntax Reference

| ❌ Don't use                            | ✅ Use instead                                 |
| --------------------------------------- | ---------------------------------------------- |
| `CASE WHEN ... THEN ... END`            | `multiIf(cond, val, cond2, val2, default)`     |
| `properties['$pathname']`               | `properties.$pathname`                         |
| `toInt32OrNull()`, `toInt64()`          | `toInt()`                                      |
| `toFloat64OrNull()`                     | direct numeric comparison                      |
| `JOIN persons p ON p.id = e.person_id`  | `person.properties.*` directly on events table |
| `team_id` as alias                      | use `org_id` or any other alias                |
| `group_properties('organization', ...)` | `$groupidentify` event + `properties.$group_0` |
| Large IN subqueries                     | explicit value lists                           |

### Key validated facts

- **MRR field:** `properties.forecasted_mrr` on `billing log` events where `log_type = 'upcoming invoice forecasted mrr'`
- **Org ID on person:** `person.properties.organization_id`
- **Org name:** `argMax(JSONExtractString(properties.$group_set, 'name'), timestamp)` on `$groupidentify` events
- **NPS event:** `survey sent` with `properties.$survey_response` (string, cast with `toInt()`)
- **Weekday filter:** `toDayOfWeek(timestamp) NOT IN (6, 7)` — 6=Saturday, 7=Sunday in ClickHouse
- **Memory limit mitigation:** break large queries into CTEs with UNION ALL; process ≤20 distinct_ids per lookup query
