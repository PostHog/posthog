# Audit: `/api/event/values` calls missing `event_name`

The `/api/event/values?key=X` endpoint is ~10x faster when at least one `event_name` is included.
Without it, ClickHouse scans all events for the last 7 days.
With it, the query adds `AND event = 'X'` which leverages the table's sort key `(team_id, toDate(timestamp), event, ...)`.

This document audits every frontend call site,
categorizes them,
and proposes a fix strategy for both frontend and backend.

---

## How it works today

### Data flow

```
PropertyFilters (component)
  └─ eventNames prop (string[])
      └─ TaxonomicPropertyFilter
          └─ PropertyValue (component)
              └─ propertyDefinitionsModel.loadPropertyValues({ eventNames })
                  └─ constructValuesEndpoint()
                      └─ GET /api/event/values?key=X&event_name=Y
                          └─ PropertyValuesQueryRunner (HogQL)
                              └─ ClickHouse: SELECT DISTINCT properties.'X' FROM events WHERE ...
```

### Backend details

- **Query runner**: `posthog/hogql_queries/property_values_query_runner.py`
- **Lookback**: fixed 7 days (not configurable)
- **Cache**: 6-hour staleness threshold (`RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS`)
- **HTTP cache**: only 10 seconds (`Cache-Control: max-age=10`)
- **ClickHouse table order**: `(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`
- **Result limit**: 10 distinct values (hardcoded)

### The difference

| | Without `event_name` | With `event_name` |
|---|---|---|
| WHERE clause | `team_id + timestamp range + property IS NOT NULL` | same + `AND event = 'X'` |
| Scan scope | All events for 7 days | Only matching events for 7 days |
| Typical latency | 1-10s | 100ms-1s |
| Leverages sort key | Partially (team_id, date) | Fully (team_id, date, **event**) |

---

## Call site audit

### Category A: Event context available — should pass `event_name` (HIGH IMPACT)

These sites have a known event context nearby but don't pass it through.

| # | File | Line | Context | Available event name(s) | Fix |
|---|------|------|---------|------------------------|-----|
| A1 | `frontend/src/lib/components/UniversalFilters/UniversalFilters.tsx` | 114 | Universal filter bar (session recordings, error tracking, etc.) | The `filter` object is an `UniversalFilterValue` which has event entity info | Extract event name from `filter` and pass as `eventNames` |
| A2 | `frontend/src/scenes/hog-functions/filters/HogFunctionFilters.tsx` | 230 | Hog function (destination/webhook) property filters | Parent has `currentFilters?.events` array with event matchers containing event names | Collect event names from `currentFilters.events` and pass down |
| A3 | `frontend/src/scenes/hog-functions/filters/HogFunctionFiltersInternal.tsx` | 136 | Hog function internal filters | Same — event matchers are available in the parent component | Collect event names from event matchers |
| A4 | `products/workflows/frontend/Workflows/hogflows/filters/HogFlowFilters.tsx` | 101 | HogFlow action filters | The parent `HogFlowAction` has event info from the trigger step | Pass event name from action context |

### Category B: Cross-event context — no event name appropriate (LOW IMPACT, needs backend fix)

These sites genuinely apply across all events. No single event name makes sense.

| # | File | Line | Context | Why no event name |
|---|------|------|---------|-------------------|
| B1 | `frontend/src/scenes/settings/environment/TestAccountFiltersConfig.tsx` | 114 | Global test account filters | Intentionally matches ALL events |
| B2 | `frontend/src/scenes/dashboard/DashboardEditBar.tsx` | 122 | Dashboard-level property filters | Apply to all insights on the dashboard |
| B3 | `frontend/src/scenes/dashboard/TileFiltersOverride.tsx` | 57 | Per-tile filter overrides | Override applies to whatever insight is on the tile |
| B4 | `frontend/src/scenes/data-pipelines/batch-exports/BatchExportConfiguration.tsx` | 322 | Batch export filters | Exports can cover multiple event types |
| B5 | `frontend/src/scenes/settings/environment/UsageMetricsConfig.tsx` | 206 | Usage metrics config filters | Cross-event usage tracking |

### Category C: Product-specific context — could hardcode known event names (MEDIUM IMPACT)

These are product-specific UIs where the relevant events are well-known.

| # | File | Line | Context | Suggested event name(s) | Fix |
|---|------|------|---------|------------------------|-----|
| C1 | `products/llm_analytics/frontend/LLMAnalyticsScene.tsx` | 79 | LLM analytics property filters | `$ai_generation`, `$ai_metric` | Hardcode `['$ai_generation']` or derive from query |
| C2 | `products/llm_analytics/frontend/clusters/ClusteringSettingsPanel.tsx` | 44 | LLM clustering config | `$ai_generation` | Hardcode `['$ai_generation']` |
| C3 | `products/llm_analytics/frontend/clusters/ClusteringAdminModal.tsx` | 95 | LLM clustering admin | `$ai_generation` | Hardcode `['$ai_generation']` |
| C4 | `products/llm_analytics/frontend/evaluations/components/EvaluationTriggers.tsx` | 147 | LLM evaluation triggers | `$ai_generation` | Hardcode `['$ai_generation']` |
| C5 | `products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/rules/Rules.tsx` | 270 | Error tracking rules | `$exception` | Hardcode `['$exception']` |
| C6 | `products/revenue_analytics/frontend/RevenueAnalyticsFilters.tsx` | 196 | Revenue analytics filters | Revenue-specific events (e.g. `purchase`, `$stripe_event`) | Pass relevant revenue event names |

### Category D: Non-event property types (NOT AFFECTED)

These use different endpoints — the `/api/event/values` issue doesn't apply.

| # | File | Line | Context | Why not affected |
|---|------|------|---------|-----------------|
| D1 | `frontend/src/queries/nodes/SessionsNode/SessionPropertyFilters.tsx` | 43 | Session properties | Uses `/api/environments/{id}/sessions/values` |
| D2 | `frontend/src/queries/nodes/PersonsNode/PersonPropertyFilters.tsx` | 19 | Person properties | Uses `/api/person/values` |
| D3 | `frontend/src/scenes/feature-flags/FeatureFlagReleaseConditions.tsx` | 343 | Feature flag targeting | Primarily person/group properties, not event properties |
| D4 | `frontend/src/scenes/feature-flags/FeatureFlagReleaseConditionsCollapsible.tsx` | 416 | Feature flag targeting (collapsible) | Same as above |
| D5 | `products/workflows/frontend/Workflows/hogflows/steps/StepTrigger.tsx` | 479 | Workflow batch trigger conditions | Uses person/cohort/feature flag property types |
| D6 | `products/workflows/frontend/Workflows/hogflows/steps/StepTrigger.tsx` | 724 | Workflow conversion filters | Uses person/cohort property types |

### Already correct (reference)

These sites already pass `eventNames` properly.

| File | Line | eventNames source |
|------|------|-------------------|
| `ActionFilterRow.tsx` | 908 | `filter.id` (selected event) |
| `ActionFilterRow.tsx` | 691 | `name` (filter name for math property) |
| `ActionFilterGroup.tsx` | 186 | All nested filter names |
| `WebAnalyticsFilters.tsx` | 446 | `['$pageview']` |
| `WebPropertyFilters.tsx` | 93 | `['$pageview']` |
| `SurveyResponseFilters.tsx` | 256 | `[SurveyEventName.SENT]` |
| `SurveyEventTrigger.tsx` | 208 | `[event.name]` |
| `ExceptionFilters.tsx` | 51 | `['$exception']` |
| `CohortField.tsx` | 235 | `criteria?.key` |
| `EventPropertyFilters.tsx` | 38-43 | `query.event` |
| `GlobalAndOrFilters.tsx` | 46 | `getAllEventNames()` |
| `AutoShowSection.tsx` | 157 | `[event.name]` |
| `TaxonomicBreakdownPopover.tsx` | 86 | `allEventNames` |

### Also in `taxonomicFilterLogic.tsx` — hardcoded `valuesEndpoint` without event_name

| Line | Group type | valuesEndpoint | Has event_name? |
|------|-----------|----------------|-----------------|
| 510-512 | EventMetadata | `api/event/values/?key=X&is_column=true` | **NO** |
| 750 | PageviewUrls | `...?key=$current_url&event_name=$pageview` | Yes |
| 762 | PageviewEvents | `...?key=$current_url&event_name=$pageview` | Yes |
| 777 | Screens | `...?key=$screen_name&event_name=$screen` | Yes |
| 789 | ScreenEvents | `...?key=$screen_name&event_name=$screen` | Yes |
| 813 | AutocaptureEvents | `...?key=$el_text&event_name=$autocapture` | Yes |

The **EventMetadata** `valuesEndpoint` (line 510) is missing `event_name` but uses `is_column=true`,
which queries metadata columns (timestamp, uuid, etc.) rather than JSON properties.
This is less impactful since column-based queries are already fast.

### Bug: Double URL concatenation in Replay valuesEndpoint

At `taxonomicFilterLogic.tsx:985-993`,
the `valuesEndpoint` for the Replay group concatenates two URL paths:

```typescript
valuesEndpoint: (key) => {
    if (key === 'visited_page') {
        return (
            `api/environments/${teamId}/events/values/?key=` +
            'api/event/values/?key=' +       // <-- BUG: second URL appended as key value
            encodeURIComponent('$current_url') +
            '&event_name=' +
            encodeURIComponent('$pageview')
        )
    }
},
```

This produces a malformed URL like:
`api/environments/1/events/values/?key=api/event/values/?key=%24current_url&event_name=%24pageview`

---

## Proposed strategy

### Phase 1: Frontend quick wins (Category A + C)

These changes are small, self-contained, and each provides immediate ~10x speedup for that call site.

**Category A fixes** (extract event names from existing context):

1. **UniversalFilters.tsx** — Check if `filter` has an event entity and extract its name
2. **HogFunctionFilters.tsx** — Collect event names from `currentFilters.events` matchers
3. **HogFunctionFiltersInternal.tsx** — Same pattern
4. **HogFlowFilters.tsx** — Extract event name from the parent action context

**Category C fixes** (hardcode known event names):

5. **LLMAnalyticsScene.tsx** — `eventNames={['$ai_generation']}`
6. **ClusteringSettingsPanel.tsx** — `eventNames={['$ai_generation']}`
7. **ClusteringAdminModal.tsx** — `eventNames={['$ai_generation']}`
8. **EvaluationTriggers.tsx** — `eventNames={['$ai_generation']}`
9. **ErrorTracking Rules.tsx** — `eventNames={['$exception']}`
10. **RevenueAnalyticsFilters.tsx** — Pass revenue-specific event names

**Bug fix**:

11. **taxonomicFilterLogic.tsx:985-993** — Fix double URL concatenation in Replay valuesEndpoint

### Phase 2: Backend optimizations (Category B + general)

For call sites where no event name is available, optimize the backend:

#### 2a. Increase HTTP cache duration

**File**: `posthog/api/event.py` line 628
- **Current**: `Cache-Control: max-age=10` (10 seconds)
- **Proposed**: `Cache-Control: max-age=300` (5 minutes)
- **Impact**: Reduces repeated identical requests from the same browser session.
  Property value suggestions don't change frequently enough to need 10-second freshness.

#### 2b. Use property definitions table as a fast fallback

When no `event_name` is provided,
instead of scanning the `events` table,
query the `posthog_propertydefinition` table (Postgres) or a pre-aggregated ClickHouse table
that already tracks known property values.
This would be near-instant but might return slightly stale results.

**Trade-off**: Results may not reflect the very latest data (last few hours),
but for autocomplete suggestions this is usually acceptable.

#### 2c. Add a `PREWHERE` optimization

**File**: `posthog/hogql_queries/property_values_query_runner.py`
- When `event_name` IS provided, ensure the event filter uses ClickHouse's `PREWHERE` clause
  (which filters before reading the full row from disk).
- The current HogQL path puts it in `WHERE`.
  Moving to `PREWHERE` would reduce I/O significantly.

#### 2d. Leverage materialized columns

**File**: `posthog/hogql_queries/property_values_query_runner.py`
- The HogQL path always uses `properties.'key'` → `JSONExtractRaw()`
- The legacy SQL path (`posthog/queries/property_values.py`) checks for materialized columns first
- Adding materialized column detection to the HogQL path would speed up queries
  for commonly-used properties like `$current_url`, `$browser`, etc.

#### 2e. Configurable lookback period

**File**: `posthog/hogql_queries/property_values_query_runner.py` line 116
- Currently hardcoded to 7 days
- Could accept an optional `lookback_days` parameter (default 7, max 30)
- Shorter lookback (e.g. 1 day) would be much faster for high-volume projects

### Phase 3: Consider architectural changes

#### 3a. Pre-aggregate property values

Run a periodic background job that maintains a `property_values_cache` table:
```sql
CREATE TABLE property_values_cache (
    team_id UInt64,
    event_name String,
    property_key String,
    property_value String,
    last_seen DateTime
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (team_id, event_name, property_key, property_value)
```

This would make ALL property value lookups fast regardless of whether `event_name` is provided.

#### 3b. Frontend debounce + caching layer

Add a client-side cache in `propertyDefinitionsModel` that deduplicates requests:
- If the same `(key, eventNames)` was fetched in the last 5 minutes, return cached results
- This prevents redundant API calls when switching between filters

---

## Implementation priority

| Priority | Change | Impact | Effort |
|----------|--------|--------|--------|
| P0 | Fix Replay valuesEndpoint bug (line 985) | Correctness fix | 5 min |
| P1 | Category C hardcoded event names (5 call sites) | ~10x faster for LLM analytics, error tracking, revenue | 30 min |
| P1 | Category A extract event names (4 call sites) | ~10x faster for universal filters, hog functions, workflows | 1-2 hours |
| P2 | Increase HTTP cache to 5 min | Reduces load for ALL call sites | 5 min |
| P2 | Add PREWHERE optimization | Faster even with event_name | 1 hour |
| P2 | Use materialized columns in HogQL path | Faster for common properties | 2 hours |
| P3 | Property definitions table fallback | Fast fallback for no-event-name case | 1 day |
| P3 | Pre-aggregated property values table | Eliminates the problem entirely | 2-3 days |
