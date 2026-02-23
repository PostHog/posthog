# Error tracking metrics — What we're measuring & what we need to instrument

## Pillar 1: Setup

_Can I get this working and keep it working?_

---

### Source map upload success

**Metric:** % of source map uploads that succeed

If customers can't upload source maps, they can't view stack traces for minified languages and the product is questionably useful.

**Formula:** `successful uploads / total upload attempts` per org

**SQL:** `countIf(success = true) / count()` grouped by org, over time

#### Events

##### `error_tracking_source_map_upload` (backend)

| Property      | Type    | Description               |
| ------------- | ------- | ------------------------- |
| `duration_ms` | number  | Time taken for upload     |
| `file_size`   | number  | Size of uploaded file     |
| `success`     | boolean | Whether upload succeeded  |
| `file_counts` | number  | Number of files in upload |

---

### Workflow integration — external trackers

**Metric:** % of issues pushed to external trackers

Error tracking is less sticky if customers don't integrate it into their workflow.
Workflows are getting more AI-centric, so pulling exception info into AI is the emerging workflow.

**Formula:** `distinct issues pushed / distinct issues viewed` per org

**SQL:** `count(distinct issue_id) FROM error_tracking_issue_pushed / count(distinct issue_id) FROM error_tracking_issue_viewed` per org

#### Events

##### `error_tracking_issue_pushed` (frontend)

| Property      | Type   | Description                         |
| ------------- | ------ | ----------------------------------- |
| `issue_id`    | string | The issue that was pushed           |
| `destination` | string | Target tracker (linear/jira/github) |

##### `error_tracking_issue_viewed` (frontend)

| Property   | Type   | Description               |
| ---------- | ------ | ------------------------- |
| `issue_id` | string | The issue that was viewed |

> **Note:** External reference created by Hugues Pouillot — check on this.
> `error_tracking_issue_viewed` is a shared event, also used in Pillar 4.

---

### Workflow integration — fix copy prompt

**Metric:** % of issues with fix copy prompt used

**Formula:** `distinct issues with fix prompt copied / distinct issues viewed` per org

**SQL:** `count(distinct issue_id WHERE prompt_type='fix') FROM error_tracking_prompt_copied / count(distinct issue_id) FROM error_tracking_issue_viewed` per org

#### Events

##### `error_tracking_prompt_copied` (frontend)

| Property      | Type   | Description                         |
| ------------- | ------ | ----------------------------------- |
| `issue_id`    | string | The issue the prompt was copied for |
| `prompt_type` | string | Type of prompt (fix/explain)        |

##### `error_tracking_issue_viewed` (frontend)

Same as above.

---

### Alert adoption rate

**Metric:** % of orgs with ≥1 alert set up

If customers have to actively visit error tracking, it's less useful than being proactively alerted where they're already working (e.g. Slack).

**Formula:** `orgs with alerts set up / total orgs capturing exceptions`

**SQL:** compute from `error_tracking_alert_created` — distinct orgs with ≥1 event / total orgs with `$exception` events

#### Events

Alerting events already on branch:

##### `error_tracking_alert_created` (backend)

No additional props documented yet.

##### `error_tracking_alert_updated` (backend)

No additional props documented yet.

##### `error_tracking_alert_toggled` (backend)

No additional props documented yet.

##### `error_tracking_alert_deleted` (backend)

No additional props documented yet.

##### `error_tracking_alert_sent` (backend)

No additional props documented yet.

##### `error_tracking_alert_failed` (backend)

No additional props documented yet.

##### `error_tracking_alert_clicked` (blocked)

Blocked by template snapshot problem → Q2 dedicated ET alerts.

> **Open questions:**
>
> - Can we use postgres data? Sync?
> - Alert count should be a proper event/metric (backend)?
> - Backfill challenge: if we create a new metric, backfilling existing orgs (~1500 alerts created on prod US). Aleksander to look into this.
> - Ideally track alerts when fired (e.g. CDP alert).

---

### Alerting creation conversion

**Metric:** % converting from alerting page viewed → alert created

If creating alerts isn't easy / high conversion, people won't create them and the product is less sticky.

**Formula:** funnel: `error_tracking_alerting_page_viewed` → `error_tracking_alert_created`

**SQL:** PostHog funnel insight, not raw SQL

#### Events

##### `error_tracking_alerting_page_viewed` (frontend)

No additional props needed.

##### `error_tracking_alert_created` (backend)

Already on branch — same as above.

> **Note:** Only 5% of ET users have alerts.
> Survey opportunity: when spike detected + no alert configured → prompt "want alerts for spikes like this?" (recommendation center).

---

## Pillar 2: User experience

_Is using this product fast and pleasant to use?_

---

### Issue list load time

**Metric:** p50 and p95 issue list load time

A slow product is a painful product.

**Formula:** `percentile(duration_ms, 0.5)` and `percentile(duration_ms, 0.95)` per org, over time

**SQL:** `quantile(0.5)(duration_ms), quantile(0.95)(duration_ms) FROM error_tracking_issue_list_loaded` — break down by `cached` to compare

#### Events

##### `error_tracking_issue_list_loaded` (frontend)

| Property          | Type    | Description                           |
| ----------------- | ------- | ------------------------------------- |
| `duration_ms`     | number  | Time to load the issue list           |
| `cached`          | boolean | Whether result was served from cache  |
| `result_count`    | number  | Number of issues returned (suggested) |
| `filters_applied` | number  | Number of active filters (suggested)  |

> **Note:** Check with infra/ClickHouse team — query engine may already expose timing + cache status. If so, we may not need a custom event.

---

### Stack trace load time

**Metric:** p50 and p95 stack trace load time

Waiting for a stack trace to load slows down a workflow and is painful.

**Formula:** `percentile(duration_ms, 0.5)` and `percentile(duration_ms, 0.95)` per org, over time

**SQL:** `quantile(0.5)(duration_ms), quantile(0.95)(duration_ms) FROM error_tracking_stack_trace_loaded`

#### Events

##### `error_tracking_stack_trace_loaded` (frontend)

| Property      | Type   | Description                           |
| ------------- | ------ | ------------------------------------- |
| `duration_ms` | number | Time to load the stack trace          |
| `issue_id`    | string | The issue this stack trace belongs to |
| `frame_count` | number | Number of frames in the stack trace   |

> **Notes:**
>
> - Only send event on FIRST stack trace load per issue view.
> - Consider preloading stack trace on mouse hover of issue.
> - Use past tense naming convention.

---

### Error tracking UI error rate

**Metric:** error-affected users on ET pages

If a high % of our users see errors, it's a crappy experience. If the query for issue listing doesn't complete, the whole page is useless.

**Formula:** `distinct users with exceptions on ET pages / distinct users visiting ET pages` per period

#### Events

No new custom events needed. Manually capture `$exception` events on ET pages (currently only autocapturing). May be able to filter based on exception values.

> **Note:** We should also fix the noisy #alerts-error-tracking Slack channel.
> We should show most buggy page across all of PostHog.

---

### Source map resolution rate

**Metric:** % of frames with resolved source (for errors where source maps should exist, e.g. not Python, uploaded)

Even when uploads succeed, frames may not resolve correctly (wrong version, wrong file mapping, vendor code). This measures whether stack traces are actually useful to the customer.

**Formula:** `resolved frames / total frames that should have source maps` (exclude Python etc.) per org

**SQL:** if per-exception: `avg(resolved_frame_count / total_resolvable_frame_count)` per org

#### Events

Add properties to the existing `error_tracking_stack_trace_loaded` event. Only measure when someone LOADS the issue.

##### `error_tracking_stack_trace_loaded` (frontend) — additional properties

| Property                       | Type   | Description                               |
| ------------------------------ | ------ | ----------------------------------------- |
| `resolved_frame_count`         | number | Number of frames successfully resolved    |
| `total_resolvable_frame_count` | number | Total frames that should have source maps |

> **Note:** Frame-level resolution event design TBD (@hugues) — either per-frame or one event per exception summarizing all frames.

---

### Crash-free sessions

**Metric:** sessions with 0 exceptions / total sessions

Lets customers measure whether their product is getting more stable over time. This is what makes ET feel like it's DOING something, not just showing errors. One of Sentry's most prominent retention features (release health).

**Formula:** `% of users who saw exception / % of users who visited error tracking` (with regex on error tracking URL)

#### Events

No new events needed. Use existing `$pageview` and `$exception` events.

> **Challenge:** People in one session can visit multiple products — apply regex to URL and check if exception happened on error tracking pages.

---

### Feature breadth

**Metric:** count distinct features touched per org per week

Single highest-leverage metric. Measures whether users discover and adopt the full product. Directly enables: measuring experiment impact (e.g. product tours), powering recommendation center (Q2), computing feature-level retention via breakdown. Replaces ambiguous "time on product."

**Formula:** `count(distinct feature_name)` per org per week. Can also express as %: `distinct features used / total known features`

**SQL:**

```sql
SELECT org_id, count(distinct properties.feature_name)
FROM events
WHERE event = 'error_tracking_feature_used'
  AND timestamp > now() - interval 7 day
GROUP BY org_id
```

Feature retention: use as first + return event in retention insight, breakdown by `feature_name`.

#### Events

##### `error_tracking_feature_used` (frontend)

| Property       | Type   | Description                                 |
| -------------- | ------ | ------------------------------------------- |
| `feature_name` | string | Which feature was used (see taxonomy below) |

**Feature taxonomy:**
`issue_list`, `issue_detail`, `stack_trace`, `copy_prompt_fix`, `copy_prompt_explain`, `assign`, `status`, `merge`, `suppress_rules`, `search`, `filters`, `replay_link`, `grouping_rules`, `breakdowns`

> **Requirement:** A mutation counts as "used" — not just viewing the feature but actually using it.

---

### NPS

**Metric:** NPS score trend over time

Direct user sentiment signal. Tracked over time, tells us if UX improvements actually land. Behavioral cohorts project will let us segment by user type.

**Formula:** standard NPS: `% promoters (9-10) - % detractors (0-6)` from survey responses

**Trigger:** issue detail page after 5+ issues viewed

#### Events

No custom events needed. Uses PostHog survey — analysis via PostHog survey tools, not raw SQL.

---

## Pillar 3: Signaling

_Is the product showing me signal or noise?_

---

### Suppression rate

**Metric:** % of issues suppressed

If users are constantly suppressing issues, the product is generating noise they have to manually clean up. High suppression = poor signal quality. We want this trending toward zero.

**Formula:** `issues suppressed / issues viewed` (average suppression rate on issue detail page by org)

#### Events

##### `error_tracking_issue_status_updated` (backend)

| Property         | Type   | Description                                     |
| ---------------- | ------ | ----------------------------------------------- |
| `status_updated` | string | New status value (e.g. `suppress`)              |
| `source`         | string | How it was suppressed (manual/rule/server-side) |

> **Note:** Frontend suppression probably exists, backend doesn't yet.

---

### Suppression rule saves

**Metric:** suppression rule saves count

**Formula:** `count(rule save events)` per org over time (create + update)

**SQL:** `count() FROM error_tracking_suppression_rule_saved GROUP BY org_id` — break down by `is_new` to see create vs update ratio

#### Events

##### `error_tracking_suppression_rule_saved` (frontend)

| Property  | Type    | Description                                       |
| --------- | ------- | ------------------------------------------------- |
| `rule_id` | string  | The suppression rule ID                           |
| `is_new`  | boolean | Whether this is a create (true) or update (false) |

---

### Grouping correction rate

**Metric:** rule saves + issues merged (goal: bring toward zero)

If users create custom grouping rules or manually merge issues, our grouping algo isn't working. These are workarounds for a broken default. Goal is zero — the algo should just work.

**Formula:** `count(grouping_rule_saved) + count(issue_merged)` per org per period

**SQL:** `count() FROM error_tracking_grouping_rule_saved + count() FROM error_tracking_issue_merged` per org — track separately too, because rule saves = algo failure, merges = granularity failure (different problems)

#### Events

##### `error_tracking_grouping_rule_saved` (frontend)

| Property  | Type    | Description                                       |
| --------- | ------- | ------------------------------------------------- |
| `rule_id` | string  | The grouping rule ID                              |
| `is_new`  | boolean | Whether this is a create (true) or update (false) |

##### `error_tracking_issue_merged` (frontend)

Verify this event exists and is queryable.

---

### Bill variability

**Metric:** stddev(monthly revenue) per org

Unpredictable bills cause churn even when the product works well. High revenue stddev = surprise invoices. Especially dangerous because exception volume can spike from bot traffic or a single bad deploy.

**Formula:** `stddev(monthly_revenue)` per org over trailing 6 months

**SQL:**

```sql
SELECT org_id, stddev(revenue)
FROM iwa_summary
WHERE product = 'error_tracking'
GROUP BY org_id
```

Filter out free tier (revenue = 0 every month → stddev = 0, not useful).

#### Events

No new events needed. Computed from billing data (`iwa_summary_customer_month`).

> **Note:** Assumes ET revenue is filterable by product in this table. Assigns to billing period END month, not calendar month.

---

## Pillar 4: Prioritization

_Am I successfully acting on signal?_

---

### Time to first action

**Metric:** median time from issue created to first meaningful action per org

Proxy for whether the product helps teams actually fix bugs, not just see them. If time to first action decreases, we're getting the right issues in front of the right people faster. Trend matters more than absolute value.

**Formula:** `median(min(first_action_timestamp) - issue_created_at)` per org

**Qualifying actions:** status change, copy prompt (fix), assign, create external issue
**NOT actions:** suppress, merge, view stack trace, explain prompt

**SQL:**

```sql
SELECT issue_id, min(timestamp) as first_action_at
FROM error_tracking_feature_used
WHERE feature_name IN ('status_change', 'copy_prompt_fix', 'assign')
GROUP BY issue_id
```

Then join with issue creation timestamp and compute median per org.
`error_tracking_issue_pushed` needs to be unioned in separately.

#### Events

All qualifying actions route through:

##### `error_tracking_feature_used` (frontend)

Same event as feature breadth — actions like `status_change`, `copy_prompt_fix`, `assign` are `feature_name` values.

##### `error_tracking_issue_pushed` (frontend)

Same as workflow integration — for external issue creation (linear/jira/github).

##### `error_tracking_issue_viewed` (frontend)

Needed to confirm the issue was seen. This is the issue DETAIL page view, not the list view. `error_tracking_issues_list_viewed` already exists for the list page — verify single-issue detail view event exists (may be under a different name).

> **Note:** This metric is considered overengineered — will be watched qualitatively for now.

---

### Exceptions without context

**Metric:** % of exceptions missing key context

Context is core to the PostHog error tracking value proposition. Without `session_id`, replay, logs, or stack trace, an exception is just a log line.

**Formula:** `exceptions missing session_id OR replay OR logs OR stack trace / total exceptions viewed` per org

Alternatively: when we try to load context and it's empty, send an event for that specific missing context.

#### Events

##### `error_tracking_exception_missing_context` (frontend) — proposed

| Property              | Type    | Description                    |
| --------------------- | ------- | ------------------------------ |
| `missing_session_id`  | boolean | Whether session_id is missing  |
| `missing_replay`      | boolean | Whether replay is missing      |
| `missing_logs`        | boolean | Whether logs are missing       |
| `missing_stack_trace` | boolean | Whether stack trace is missing |

> **Note:** Event design still TBD — e.g. if the session card shows nothing because there's no `session_id`, send event with the specific missing context type.
