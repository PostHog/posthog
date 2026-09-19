# Replay recording-window filter rollout

The `replay-recording-window-combined-filters` flag controls a combined event scan for recording-window list queries.
It defaults to off.
The server evaluates it locally with the team ID as the distinct ID and the deployment region as the `region` property.
Use the supplied `region` property for regional targeting; team IDs can overlap between regions.
A missing flag, an unavailable local definition, or an evaluation error selects the separate-query path.
The flag does not control whether the recording-window option appears in the UI.
The separate `replay-event-match-scope` flag controls that option.
Keep the UI flag limited to the validation audience until the internal pilot passes.

The combined path requires at least two positive event or event-property filters.
Actions, negative filters, person properties, group properties, cohort filters, custom HogQL properties, sampled scans, and scans with an extra timestamp floor use the separate-query path.
Player event highlighting and test-account exclusion queries keep their existing query paths.
The one-minute recording margin, metadata aggregation, list ordering, and cursor pagination remain in place.
Candidate-bound pushdown and removal of the outer metadata query need separate measurements before implementation.

## Measurements

The listing query writes these fields to the existing ClickHouse query tags:

| Tag                                    | Meaning                                                                       |
| -------------------------------------- | ----------------------------------------------------------------------------- |
| `replay_event_query_strategy`          | `separate` or `combined`, based on the query that actually runs               |
| `replay_combined_event_query_eligible` | Whether the request can use the combined path, independent of flag assignment |
| `replay_event_filter_count`            | Number of event-table filter expressions                                      |
| `replay_event_query_has_properties`    | Whether the filters include event properties                                  |
| `replay_event_query_operand`           | `AND` or `OR`                                                                 |
| `replay_event_query_range_days`        | Requested date range in days                                                  |

Use only eligible queries for the control comparison.
Keep regions separate.
Compare the same filter count, operand, property usage, and date-range bucket.
Check results by team as well as across teams so that one large project does not determine the outcome.
Measure successful query p50, p95, and p99 duration, read bytes, initial-query peak memory, and failure rate.
Count timeouts and memory-limit failures separately.
Also check the recording-list endpoint's existing latency and error metrics; database duration does not include all request work.

This query gives the database measurements for a region.
Bind `cluster` to that region's ClickHouse cluster name.
Use `initial_query_id` to inspect worker queries when a memory or network regression needs investigation.
Initial-query peak memory is not total cluster memory.
Keep query caches, time windows, and query-log sampling settings the same between comparisons.
Verify that successful queries and failed queries have equal log sampling before calculating failure rates.

```sql
SELECT
    strategy,
    filter_count,
    operand,
    has_properties,
    range_bucket,
    count() AS queries,
    uniqExact(team_id) AS teams,
    countIf(type != 'QueryFinish') / count() AS failure_rate,
    countIf(exception_code IN (159, 160)) AS timeouts,
    countIf(exception_code = 241) AS memory_failures,
    quantilesExactIf(0.5, 0.95, 0.99)(query_duration_ms, type = 'QueryFinish') AS duration_ms,
    quantileExactIf(0.95)(memory_usage, type = 'QueryFinish') AS initial_peak_memory_p95,
    quantileExactIf(0.95)(read_bytes, type = 'QueryFinish') AS read_bytes_p95
FROM
(
    SELECT DISTINCT
        query_id, type, exception_code, query_duration_ms, memory_usage, read_bytes,
        JSONExtractUInt(log_comment, 'team_id') AS team_id,
        JSONExtractString(log_comment, 'replay_event_query_strategy') AS strategy,
        JSONExtractUInt(log_comment, 'replay_event_filter_count') AS filter_count,
        JSONExtractString(log_comment, 'replay_event_query_operand') AS operand,
        JSONExtractBool(log_comment, 'replay_event_query_has_properties') AS has_properties,
        multiIf(
            JSONExtractFloat(log_comment, 'replay_event_query_range_days') <= 1, 'up to 1 day',
            JSONExtractFloat(log_comment, 'replay_event_query_range_days') <= 7, 'up to 7 days',
            JSONExtractFloat(log_comment, 'replay_event_query_range_days') <= 30, 'up to 30 days',
            'over 30 days'
        ) AS range_bucket
    FROM clusterAllReplicas({cluster:String}, system.query_log)
    WHERE event_date >= today() - 1
      AND event_time >= now() - INTERVAL 24 HOUR
      AND is_initial_query = 1
      AND type IN ('QueryFinish', 'ExceptionWhileProcessing', 'ExceptionBeforeStart')
      AND JSONExtractBool(log_comment, 'replay_combined_event_query_eligible')
      AND JSONExtractString(log_comment, 'replay_event_query_strategy') IN ('separate', 'combined')
)
GROUP BY strategy, filter_count, operand, has_properties, range_bucket
ORDER BY filter_count, operand, has_properties, range_bucket, strategy
```

## Release gates

The replay engineer who enables the flag owns each stage and records the query IDs, comparisons, and decision in a private release record.
The thresholds below are release criteria, not measured results.
Do not put query text, result rows, or customer-specific measurements in a public pull request.

1. **Disabled baseline:** Deploy with the combined-query flag off.
   Allow recording-window requests from an internal validation audience through the UI flag or the API.
   Collect at least 24 hours of tagged eligible queries.
   Confirm that combined queries are absent and that endpoint errors have not increased.
2. **Internal pilot:** Add an explicit internal team ID and region condition.
   Check at least 100 paired requests against fixed historical data, with both flag values.
   Cover `AND`, `OR`, two through five filters, properties on events, standalone properties, sparse recordings, and one-, seven-, and thirty-day windows.
   Compare ordered recording IDs, all metadata, `has_more_recording`, and cursors across at least two pages.
   Use the actual list query and actual replay tables.
   Run pairs sequentially with a fixed end time and alternate execution order.
   Do not run duplicate queries on the live request path.
3. **Regional rollout:** Increase to 1%, 5%, 25%, then 50% of team IDs within one region.
   Keep the same flag key so that percentage increases preserve assignment.
   Hold each stage for at least 24 hours and 1,000 eligible requests in each arm, from at least 20 teams per arm.
   Extend the hold if a common query bucket has fewer than 100 requests in either arm.
   For each query bucket, divide combined p95 duration by separate p95 duration.
   Weight these ratios by the baseline request share of each bucket, fixed before the stage starts.
   Require a weighted ratio of 0.80 or less, with no missing common buckets.
   No common bucket may regress by more than 10% in p95 duration or p95 initial-query peak memory.
   The failure rate may not increase by more than 0.1 percentage points.
   Investigate every new memory-limit failure before expansion.
   Check endpoint p95 and p99 for a regression of more than 10%.
4. **Full rollout:** Require a full seven days at 50% with the same gates before 100%.
   Apply these stages separately to each region.
   Keep the flag and separate-query path for at least two weeks after full rollout.
   Remove them only after a review of results and errors.

## Correctness and the row cap

The separate path caps each filter's session set at 1,000,000 rows before it combines the filters.
The combined path applies one 1,000,000-row cap after it combines the filters.
Neither cap specifies an order.
The two paths can therefore return different results when a cap applies, even when both implement the same filter conditions.
Do not treat a capped control result as a correctness reference.

For each paired validation query, count each control filter's matching sessions and the combined matching sessions with the cap removed in a bounded offline check.
Keep the execution timeout and memory limit in place.
Below all caps, require exact agreement.
For a cap-affected case, compare with an uncapped reference and record which result set was truncated.
Do not start percentage rollout until these cases have an explicit product decision on truncation behavior.
A count check that times out or exceeds memory is inconclusive and does not pass this gate.
The request path does not detect positive-set truncation automatically.

## Stop and rollback

Disable the flag on any unexplained result or cursor difference, a new memory-limit failure, or a sustained breach of a release gate in two consecutive 15-minute windows.
Use a full 24-hour comparison to advance a stage; a quiet 15-minute interval is not evidence of success.
Flag updates reach local SDK definitions through polling, configured at 90 seconds.
This is not a guaranteed rollback deadline if a worker cannot refresh its definitions.
Queries already in progress continue with their selected strategy.
Verify that new eligible query tags return to `separate` in every affected region.
If combined queries continue after two polling intervals, check flag refresh health and roll back the deployment if needed.
