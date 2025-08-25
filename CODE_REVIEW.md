# Code Review Report

**Branch:** feat/remove-ai-events-from-general-events  
**Base:** master  
**Files Changed:** 2 files (+142 insertions, -5 deletions)

## Critical Issues

**None identified.** No logic errors, security risks, or data corruption issues found.

## Functional Gaps

- **L471-474, L501-504: Missing index on `event` column** — The `NOT LIKE '$ai_%'` filter operates on an unindexed column. In ClickHouse, the `event` column is part of the ORDER BY clause `(team_id, toDate(timestamp), event, ...)` which provides some optimization, but for negative pattern matching this is suboptimal.
  - **Test coverage:** Comprehensive test suite added (`test_ai_events_not_double_counted`) verifying AI events are properly excluded from billable counts. Tests cover all 6 AI event types and ensure no double-counting occurs.

## Improvements Suggested

- **L474, L504: Performance optimization for NOT LIKE pattern** — Consider replacing `event NOT LIKE '$ai_%'` with a positive list approach for better performance at scale:

```diff
- AND event NOT LIKE '$ai_%'
+ AND event NOT IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding', '$ai_feedback', '$ai_metric')
```

**Rationale:** ClickHouse optimizes `NOT IN` with a constant list better than `NOT LIKE` patterns, especially when the list is small and known. The ORDER BY clause includes `event`, allowing efficient range scans with explicit values.

- **Alternative approach:** If more AI event types are expected, consider maintaining a separate lookup table or using a bloom filter index:

```sql
-- Option 1: Add bloom filter for negative matching (requires migration)
INDEX bloom_event_type event TYPE bloom_filter(0.01) GRANULARITY 1

-- Option 2: Use a subquery with positive matching (current approach is simpler)
WHERE event NOT IN (SELECT event_name FROM ai_event_types)
```

- **Query splitting consideration:** Both modified functions use the `execute_split_query` pattern which is good for handling large date ranges. The NOT LIKE filter is applied per split, which is correct.

## Positive Observations

- **Excellent test coverage:** The new test `test_ai_events_not_double_counted` thoroughly validates the exclusion logic with all 6 AI event types
- **Consistent implementation:** Both billable event functions (regular and enhanced persons) apply the same exclusion logic
- **Proper separation of concerns:** AI events are tracked separately via `get_teams_with_ai_event_count_in_period` using positive matching (`LIKE '$ai_%'`)
- **Good defensive testing:** Tests verify that regular events still increase billable count after AI events are added
- **Clean implementation:** Minimal code changes with clear intent

## Overall Assessment

**Approve** — The implementation correctly excludes AI events from billable counts while maintaining separate tracking. The code is safe and functional.

**Next steps:**
1. Consider the performance optimization from `NOT LIKE` to `NOT IN` with explicit event names for better query performance
2. Monitor query performance in production, especially as data volume grows
3. If more AI event types are added frequently, consider a more scalable filtering approach

**Performance Analysis:**

The current `NOT LIKE '$ai_%'` approach:
- ✅ Works correctly and is maintainable
- ⚠️ Requires scanning event values for pattern matching
- ⚠️ Cannot leverage bloom filters or hash indexes effectively
- ✅ Benefits from ORDER BY clause positioning of `event` column for range scans

The suggested `NOT IN (list)` approach:
- ✅ Better optimized by ClickHouse's query planner
- ✅ Can use hash lookups for the exclusion list
- ✅ More predictable performance characteristics
- ⚠️ Requires updating the list when new AI event types are added

Given that AI event types appear to be a controlled set (6 types currently), the explicit `NOT IN` approach would provide better performance while maintaining clarity.