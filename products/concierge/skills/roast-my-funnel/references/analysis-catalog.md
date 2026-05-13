# Analysis catalog

Each entry: what the analysis finds, the query shape, how to interpret it, and
what hypothesis it supports (or rules out).

Placeholders: `{funnel_id}`, `{steps}`, `{window}`, `{worst_step_event}`,
`{worst_step_index}`. Substitute from the loaded insight and the wizard.

## Always run

### 1. Step-by-step drop

**Finds:** absolute and relative drop at each step. Identifies the worst step.

Use `posthog:query-funnel` with the loaded steps and the wizard's time window.
For each step `i`:

- `dropoff_users[i] = users_at_step[i-1] - users_at_step[i]`
- `dropoff_pct[i] = dropoff_users[i] / users_at_step[i-1]`

**Worst step tie-breakers:** higher absolute drop > higher relative drop > later
in the funnel (later steps cost more — the user spent more effort to get there).

**Supports:** "the crime" section directly. Without this, there's no skill output.

### 2. Time-to-next-step

**Finds:** median seconds between each pair of steps. Slow transitions signal
friction (long forms, slow pages, decision paralysis).

```sql
WITH funnel_events AS (
    SELECT
        person_id,
        timestamp,
        event,
        properties
    FROM events
    WHERE event IN ({step_events})
      AND timestamp >= now() - INTERVAL {window} DAY
),
sequenced AS (
    SELECT
        person_id,
        event AS from_step,
        leadInFrame(event) OVER (PARTITION BY person_id ORDER BY timestamp) AS to_step,
        date_diff('second', timestamp, leadInFrame(timestamp) OVER (PARTITION BY person_id ORDER BY timestamp)) AS seconds_to_next
    FROM funnel_events
)
SELECT from_step, to_step, median(seconds_to_next) AS median_seconds, count() AS transitions
FROM sequenced
WHERE to_step IS NOT NULL
GROUP BY from_step, to_step
ORDER BY median_seconds DESC
```

**Read:** transitions >60s on a "click button" → "see next page" gap are slow.
Transitions >10 minutes usually indicate context switch / abandonment-then-return.

**Supports:** "speed / friction" hypothesis.

### 3. Path-after-drop

**Finds:** what users did after dropping at the worst step. Reveals _why_ they
left.

Use `posthog:query-paths` rooted on `{worst_step_event}`, looking forward 1–3
events. Or HogQL:

```sql
WITH droppers AS (
    SELECT DISTINCT person_id, max(timestamp) AS last_step_at
    FROM events
    WHERE event = '{worst_step_event}'
      AND timestamp >= now() - INTERVAL {window} DAY
    GROUP BY person_id
    HAVING NOT EXISTS (
        SELECT 1 FROM events e2
        WHERE e2.person_id = droppers.person_id
          AND e2.event = '{next_step_event}'
          AND e2.timestamp > last_step_at
          AND e2.timestamp <= last_step_at + INTERVAL 24 HOUR
    )
)
SELECT e.event, e.properties.$current_url AS url, count(DISTINCT e.person_id) AS users
FROM events e
JOIN droppers d ON d.person_id = e.person_id
WHERE e.timestamp BETWEEN d.last_step_at AND d.last_step_at + INTERVAL 30 MINUTE
  AND e.event != '{worst_step_event}'
GROUP BY event, url
ORDER BY users DESC LIMIT 20
```

**Read:**

- Many users go to `/pricing` or `/help` → confusion or sticker shock
- Many users go to a competitor's domain (referrer logs) → message-match failure
- Many users go back to the previous step → form error / validation issue
- Many users do nothing further → flat-out abandonment, often UX
- Many users go to support / docs → instruction problem, not UX

**Supports:** "wrong page after drop" hypothesis. Picks the _specific reason_
they bailed.

### 4. Dropper segments

**Finds:** whether droppers are concentrated in a segment that shouldn't be in
the funnel.

Run `posthog:query-trends-actors` on the worst step's drop-off, then break down
the dropper sample by:

- Device type (`$device_type`)
- Browser (`$browser`)
- OS / app version
- `utm_source` / `utm_campaign` / `$referring_domain`
- Country / region
- Plan / tier (if `plan_prop` known)
- Group / org property (B2B)

**Read:** if 80%+ of droppers share a property that's <20% of the entry cohort,
that's selection effect — fix the audience, not the page. If droppers look like
the entry cohort, it's a real UX issue.

**Supports:** "selection effect" hypothesis (rules it in or out).

## Conditional

### 5. Revenue-weighted drop

**Runs when:** project has a detected revenue signal (`$revenue` /
`revenue` / `amount` property, or `purchase` / `subscription_created` event).

**Finds:** which step's drop costs the most _money_, not just the most users.

```sql
WITH step_droppers AS (
    -- droppers at each step from the funnel analysis
    SELECT step_index, person_id FROM ...
),
person_value AS (
    SELECT person_id, sum(toFloat(properties.{revenue_prop})) AS lifetime_value
    FROM events
    WHERE event = '{revenue_event}'
    GROUP BY person_id
),
similar_user_avg AS (
    -- average value of users who DID convert through this step
    SELECT step_index, avg(lifetime_value) AS avg_value FROM ... GROUP BY step_index
)
SELECT
    sd.step_index,
    count(DISTINCT sd.person_id) AS droppers,
    avg(sua.avg_value) AS expected_value_per_dropper,
    count(DISTINCT sd.person_id) * avg(sua.avg_value) AS estimated_lost_value
FROM step_droppers sd
JOIN similar_user_avg sua USING step_index
GROUP BY step_index
ORDER BY estimated_lost_value DESC
```

**Read:** re-rank steps by `estimated_lost_value`. If the worst step by users
isn't also the worst by revenue, surface both — the report should call out
the discrepancy.

**Supports:** sharpens "the crime" section. Without revenue signal, this analysis
is skipped and noted in "Data gaps."

### 6. Sibling funnel comparison

**Runs when:** wizard requested `Comparison: sibling funnels`.

**Finds:** other funnel insights in the project and their overall conversion
rates. Reveals whether the audited funnel is uniquely bad.

List funnel insights via `posthog:insight-get` (or the insight list endpoint),
filter to `query.kind = "FunnelsQuery"`, run each one for the same window, and
compare overall conversion rates.

**Read:**

- Audited funnel conversion is the lowest → uniquely bad, audit its specifics
- Audited funnel is in the middle of the pack → "all our funnels are this shape,"
  systemic UX or instrumentation issue
- Audited funnel conversion is high → user may be looking for problems that
  aren't there. Caveat the headline.

**Supports:** "comparable peers are fine" hypothesis (rules it in or out).

### 7. Prior period comparison

**Runs when:** wizard requested `Comparison: prior period`.

**Finds:** whether the funnel got worse, stayed flat, or got better. Frames the
narrative ("you broke this in the last 30 days" vs "this has always been bad").

Run the same funnel for the immediately-preceding window of the same length.
Compare per-step conversion.

**Supports:** sets the tense of the headline roast. "Step 3 has _always_ been a
mess" hits different from "step 3 _just_ started leaking."

## Skip conditions

Skip an analysis entirely (and note in "Data gaps") when:

- The required signal doesn't exist (revenue, sibling funnels, etc.)
- The step volume is too low for statistical signal (suggested threshold: <50
  users entering the step in the window)
- The wizard's off-limits list excludes the segment/property the analysis would
  break on
