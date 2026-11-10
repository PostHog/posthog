---
name: investigating-customer-query-problems
description: Use when a customer, CS ticket, or Slack thread reports PostHog queries failing, timing out, getting rejected (ClickHouseAtCapacity, code 202, 159 TIMEOUT_EXCEEDED, 429 throttled), returning truncated rows, or putting heavy load on ClickHouse, from MCP, PostHog AI, a personal API key, endpoints, or the app. Also use when deciding whether a customer's recurring queries should be rewritten, materialized as a view or endpoint, or cached, or when writing them a handoff about it.
---

# Investigating customer query problems

## Overview

Each query path has its own limits, and most customer complaints are a recurring job meeting one of them.
Start with a census of everything the org ran, split by path and outcome. Then name each job, measure it, and fix it at the cheapest layer.

Every number you send comes from a query you ran. Every limit or behavior you describe comes from prod or from code on current master that you read in this session. This skill tells you where to look. It doesn't give you values to repeat, and neither does your memory.

REQUIRED SUB-SKILL: use querying-production-databases to run SQL on prod, with querying-production-databases-via-metabase as the fallback. For query-level tuning (skip indexes, `FINAL`, `JSONExtract`), use optimizing-clickhouse-and-hogql-queries.

## Workflow

1. Frame the case. Collect the org ID, team IDs, region, symptom, rough start date, and which path the customer uses. Pick a window that covers before and after the start.
2. Run the census (`references/queries.md` section 1). Split by access path, sync vs async (`lc_kind`), ClickHouse user, and exception code.
3. Check what changed on our side at the start date: `git log origin/master --since <date>` on the files in `references/limits.md`, and the kill switch.
4. For each failure code, find the limit behind it with `references/limits.md`. Confirm its value in prod or on `origin/master` before you rely on it.
5. Group queries into jobs: literal-stripped shapes, cadence, daily trend (sections 2 to 4). For each job, write one line: what it computes, how often, its share of the org's CPU or read bytes, its failure rate, and whether its cost is growing.
6. Find out whether the customer caused each failure or was a victim of other load.
   - For capacity rejections (202, 439), measure fan-out and run the blame replay (sections 5 and 6).
   - For timeouts (159), compare the job's read bytes per run with its duration per GiB over the days. Rising read bytes means their window grows. A flat read with a rising duration means the cluster got slower, so check other teams on the same path.
   - Paths can run as different ClickHouse users on different clusters. Check which user and cluster each failing path used before you blame one cause for both.
7. Fix each job in this order, and see `references/fixes.md`:
   - Rewrite it, when a cheaper query gives the same rows.
   - Materialize it as a view or endpoint, when the customer can accept a fixed freshness.
   - Leave it alone, when it is cheap or already near its limit for a good reason.
8. Prove each fix on prod before you suggest it. Compile it, compare fingerprints with the original, and measure cost and fan-out (section 9).
9. Write the customer handoff (`references/handoff.md`) and the internal reply. Load writing-user-facing-copy for the handoff.

## Quick reference

| Symptom                                       | Where to look first                                                                                                                               |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| MCP or PostHog AI `ClickHouseAtCapacity`      | ClickHouse user concurrency: census, then fan-out and blame replay                                                                                |
| API key code 159                              | the sync time cap in prod (`max_execution_time` in the compiled SQL), then shapes plus daily trend                                                |
| API key 429                                   | request throttles and our Redis concurrency limiters. 429s never reach `query_log`, so use queries.md section 7 and the Prometheus limiter metric |
| Results stop at the same round number of rows | the default and max row limits for that path's `LimitContext`                                                                                     |
| Same query text every few minutes             | exact-repeat gaps (section 8) against the SQL cache freshness                                                                                     |

## Common mistakes

- Quoting a limit, cache lifetime, or code path from memory or from this skill. Read it in prod or on `origin/master`. The working tree may be an old branch.
- Comparing archive rows with live `query_log` rows as if they were the same unit. An archive row is a whole query chain with counters summed over every node.
- Reading cache freshness from `cache_target_age`. It sets the stored target age. Hits are decided in `_is_stale`.
- Telling a customer to switch to async to get around the sync time cap. If async gets a longer cap, report that internally.
- Scanning `clusterAllReplicas(..., query_log)` over hours. The call can time out while the query keeps running. Use `posthog.query_log_archive` for anything past a few hours. Use the live table only for short windows or fields the archive lacks.
- Nesting `clusterAllReplicas` inside `IN (SELECT ...)`. It fans out twice and your read-only user can get 202. Scan once and use window functions.
- Timing with `event_time`. It is the finish time. Use `query_start_time(_microseconds)`.
- Calling a query "fixed" from one sample. Check `uniqExact(cityHash64(lc_query__query))` across runs before you say the text repeats.
- Saying "no time filter" or "N properties" from a truncated sample. Read the full text of several runs.
- Treating the same row count as the same result. A `now()`-relative or open-ended window returns new values with the same text and row count.
- Pasting customer end-user emails, distinct IDs, or person IDs into the handoff or Slack. Write `<email>` or `<uuid>`.
