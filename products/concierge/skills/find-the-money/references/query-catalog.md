# Query catalog

Each entry: what the analysis finds, how to query it, how to interpret the result,
and how to phrase the finding in the report.

HogQL snippets use `{revenue_event}`, `{revenue_prop}`, `{plan_prop}`, `{window}` as
placeholders. Substitute them from the wizard answers / autodetected signals.

## Cross-cutting — always run

### A. Whale concentration

**Finds:** what share of revenue comes from the top 10% of payers.

```sql
WITH per_person AS (
    SELECT person_id, sum(toFloat(properties.{revenue_prop})) AS rev
    FROM events
    WHERE event = '{revenue_event}'
      AND timestamp >= now() - INTERVAL {window} DAY
    GROUP BY person_id
),
ranked AS (
    SELECT rev, ntile(10) OVER (ORDER BY rev) AS decile
    FROM per_person
)
SELECT decile, sum(rev) AS decile_rev, count() AS users
FROM ranked GROUP BY decile ORDER BY decile DESC
```

**Read:** top decile share. >60% = highly concentrated (whale-driven). 20–40% =
healthy long tail. <20% = unusually flat distribution, double-check the data.

**Phrase:** "Top 10% of payers generate X% of revenue (N users). Treat this cohort
as the retention floor — losing any of them moves the metric."

### B. Segment ROI

**Finds:** revenue per user by `utm_source`, country, plan, group property. Reveals
under-invested high-ROI channels and oversold low-ROI ones.

```sql
SELECT
    properties.{dimension} AS segment,
    count(DISTINCT person_id) AS users,
    sum(toFloat(properties.{revenue_prop})) AS rev,
    sum(toFloat(properties.{revenue_prop})) / count(DISTINCT person_id) AS rev_per_user
FROM events
WHERE event = '{revenue_event}'
  AND timestamp >= now() - INTERVAL {window} DAY
GROUP BY segment
HAVING users >= 30
ORDER BY rev_per_user DESC
LIMIT 20
```

**Read:** look for segments with rev_per_user 2×+ the median but small user counts
— those are under-invested. And segments with the most users but rev_per_user below
the median — those are the cost-heavy lanes.

**Phrase:** "Channel/segment {X} drives Y× the median revenue-per-user from only Z
users. Shifting spend toward this channel is likely a high-leverage move."

## Grow new revenue

### C. Conversion leak

**Finds:** the step in the signup → first-purchase funnel where the most money
walks away. High-intent users who almost paid.

Use `posthog:query-funnel` with steps: signup → key onboarding event → pricing page
view → checkout started → purchase. Look for the step with the highest drop AND the
highest _value_ of dropped users (run drop-off cohort through whale-concentration
analysis to check value).

**Read:** prioritize the step where dropped users look like future whales (high
engagement, paid-plan-shaped behavior).

**Phrase:** "{N} users hit checkout in the last {window} days but didn't complete.
Their pre-drop behavior matches the top decile of payers — this is the highest-
value leak in the funnel."

### D. Channel ROI

**Finds:** which acquisition channel produces the highest revenue per user — and
which produces volume without value.

Same query shape as **B. Segment ROI** with `dimension = utm_source` (or
`utm_campaign`, `referring_domain`). Restrict to first-touch attribution if a
`$initial_referring_domain` property exists.

**Phrase:** "{Channel X} produces Y× the revenue-per-user of {channel Y} despite
N× lower spend. Underweighted in the current acquisition mix."

### E. Time-to-value gap

**Finds:** the segment with the longest gap between signup and first revenue —
i.e. where onboarding is leaving money on the table.

```sql
WITH first_event AS (
    SELECT person_id, min(timestamp) AS signed_up
    FROM events WHERE event = '$identify' OR event = 'sign_up'
    GROUP BY person_id
),
first_revenue AS (
    SELECT person_id, min(timestamp) AS first_paid
    FROM events WHERE event = '{revenue_event}'
    GROUP BY person_id
)
SELECT
    properties.{segment_prop} AS segment,
    avg(date_diff('day', signed_up, first_paid)) AS avg_days_to_pay,
    count() AS users
FROM first_event JOIN first_revenue USING person_id
JOIN persons p ON p.id = person_id
WHERE first_paid IS NOT NULL
GROUP BY segment
HAVING users >= 20
ORDER BY avg_days_to_pay DESC
```

**Phrase:** "Users in {segment} take {N}× longer to reach first payment than the
median. Shortening this delay is the most direct revenue lever for this cohort."

### F. Pricing-page autopsy

**Finds:** users who visited `/pricing` (or equivalent) but didn't convert, broken
down by what they were doing before. Reveals whether the pricing page is the
bottleneck or whether they bounced for unrelated reasons.

Query pageviews on the pricing page, break down conversion rate by the prior event,
prior session length, and traffic source.

**Phrase:** "{N} users viewed pricing without converting. {X%} bounced within {Y}
seconds — likely a pricing-page UX or message-match issue rather than product fit."

## Expand existing

### G. Feature → upgrade correlation

**Finds:** which product features users on lower tiers use most before upgrading.
That feature is the strongest upsell hook.

```sql
WITH upgraders AS (
    SELECT person_id, min(timestamp) AS upgraded_at
    FROM events
    WHERE event = 'plan_upgraded'  -- or detect from plan_prop change
    GROUP BY person_id
),
prior_activity AS (
    SELECT u.person_id, e.event, count() AS n
    FROM upgraders u
    JOIN events e ON e.person_id = u.person_id
    WHERE e.timestamp BETWEEN u.upgraded_at - INTERVAL 14 DAY AND u.upgraded_at
    GROUP BY u.person_id, e.event
)
SELECT event, count(DISTINCT person_id) AS upgraders_using
FROM prior_activity
GROUP BY event ORDER BY upgraders_using DESC LIMIT 20
```

Compare to base-rate event frequency among non-upgraders. The events with the
biggest lift over base rate are the upsell hooks.

**Phrase:** "Users of {feature X} upgrade at {N}× the rate of non-users. Promoting
this feature to free-tier users matching the same usage shape is a clean upsell
play."

### H. Tier squeeze

**Finds:** users on a lower tier who are hitting plan limits — they're already
over-extracting value and would convert with the right nudge.

Look for `limit_reached`, `quota_exceeded`, `paywall_shown`, or feature-blocked
events filtered to lower-tier persons. Rank by frequency per user.

**Phrase:** "{N} users on {tier X} hit a plan limit {Y}+ times in the last {window}.
These are explicit upgrade signals being left on the table."

### I. Free-to-paid lookalikes

**Finds:** free users whose behavior matches the top decile of paid users — i.e. a
lookalike cohort for a marketing or sales campaign.

Define a "paid-user signature" from a handful of high-signal events (sessions per
week, feature breadth, team-collab events). Score free users against it.

**Phrase:** "{N} free users behave like the top decile of payers (same feature
breadth, same session frequency). This is the closest cohort to ready-to-buy you
have — prime for a targeted offer."

## Save at-risk revenue

### J. Dormant payers

**Finds:** paid users whose activity has dropped sharply in the last 30 days.
Predictive of churn at renewal.

```sql
WITH activity AS (
    SELECT
        person_id,
        countIf(timestamp >= now() - INTERVAL 30 DAY) AS recent,
        countIf(timestamp BETWEEN now() - INTERVAL 90 DAY AND now() - INTERVAL 30 DAY) / 2.0 AS prior_avg
    FROM events
    GROUP BY person_id
)
SELECT person_id, recent, prior_avg, prior_avg - recent AS drop
FROM activity
JOIN persons p ON p.id = person_id
WHERE p.properties.{plan_prop} IN ('paid', 'pro', 'business')
  AND prior_avg > 10
  AND recent < prior_avg * 0.3
ORDER BY drop DESC LIMIT 100
```

**Phrase:** "{N} paid users dropped >70% in activity in the last 30 days. Surface
to CS / lifecycle for proactive outreach before renewal."

### K. Engagement decline by cohort

**Finds:** monthly cohorts whose week-N retention has been declining. Reveals
product changes that broke the new-user activation funnel — losing future revenue
before it appears in the dashboards.

Use `posthog:query-retention` with monthly cohorts over 6–12 months. Look for a
visible step-down in week-2 or week-4 retention.

**Phrase:** "Week-{N} retention dropped from {X%} to {Y%} starting {month}. If this
holds, expected ARR loss compounds; investigate what changed in that window."

### L. Power-user churn risk

**Finds:** top-decile users from the whale analysis (A) who appear in the dormant
list (J) — these are the highest-priority retention cases.

Intersection of (A.top_decile) ∩ (J.dormant). Almost always a small, hand-actionable
list.

**Phrase:** "{N} top-decile customers (combined revenue {X% of total}) have gone
dormant. Each name is a hand-fixable retention case."

## Ads / advertiser ROI (alternate "expand" focus)

### M. Advertiser yield

**Finds:** revenue per impression by advertiser / campaign / inventory unit. Reveals
yield gaps in the ad inventory.

```sql
SELECT
    properties.advertiser AS advertiser,
    sum(toFloat(properties.{revenue_prop})) / count() AS yield_per_impression,
    count() AS impressions
FROM events
WHERE event = 'ad_impression'
  AND timestamp >= now() - INTERVAL {window} DAY
GROUP BY advertiser
HAVING impressions >= 1000
ORDER BY yield_per_impression DESC
```

**Phrase:** "{Advertiser X} yields {N}× the per-impression revenue of the median.
Allocating more inventory toward this advertiser is a direct yield gain."
