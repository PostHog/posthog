# flag_evaluations parity spot check

Run this by hand before widening the flag-evaluations fork to more teams. It answers one question: for a given day and a given set of teams, does every `$feature_flag_called` event in the events table also have a row in `flag_evaluations`, and vice versa.

Nothing else answers it. The fork's counters increment when Kafka acknowledges the produce, so they see nothing past that point: the Kafka engine table, the materialized view, the writable Distributed table, and the shard are all unobserved. `kafka_flag_evaluations` also sets `kafka_skip_broken_messages`, so a malformed row is dropped after a successful produce. Comparing the two tables is the only thing that catches either.

See [`sql.py`](./sql.py) for the table family and the schema this compares against.

## What to pass

Two inputs, both explicit.

**The day.** One completed UTC day, as `YYYY-MM-DD`. Not today: a partial day reads as a deficit for every event that has not been written yet.

**The team ids being widened to.** The allowlist lives only in the Node deployment env config (`INGESTION_FLAG_EVALUATIONS_TEAMS`, `INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS`, `INGESTION_FLAG_EVALUATIONS_MODE`), and nothing in ClickHouse records it. A team that is enabled but writing nothing at all looks identical to a team that was never enabled, so the check cannot derive its own team list. Pass the ids you intend to switch on.

Team ids are per region, so run each region separately and do not mix ids between them.

Skip a team on the day it was switched on. Its events from before the allowlist reached the pods have no fork row, so that day reports a large deficit for a fork that is working. Check its first full day instead.

## Running it

Run the query against the ClickHouse database in production Metabase, one region at a time. Metabase sits behind ALB Cognito OAuth, so a browser session is the shortest path: open Metabase for the region, start a native query, pick the ClickHouse database, and paste the query below.

From a terminal, `hogli metabase:query` does the same thing:

```bash
hogli metabase:login --region us
hogli metabase:databases --region us --format json   # database ids change when Metabase metadata is rebuilt
hogli metabase:query --region us --database-id <id> --file parity.sql --save results.json
```

An agent running this should invoke the `metabase-prod-query` skill instead, which wraps the same commands.

Results name customer teams, so keep them in a file or in Metabase. Do not paste them into a PR, an issue, or any other public place.

Batch the team list at around 20 teams per query. The query's memory scales with the rows in the batch, not with the number of teams, so one batch containing a high-volume team is what runs it out of memory.

## The query

Substitute the day and the batch of team ids.

```sql
SELECT
    team_id,
    countIf(in_ev > 0 AND in_fe = 0) AS only_in_events,
    countIf(in_fe > 0 AND in_ev = 0) AS only_in_flag_evaluations,
    countIf(in_fe > 0 AND in_ev > 0) AS in_both
FROM (
    SELECT team_id, uuid, max(is_fe) AS in_fe, max(is_ev) AS in_ev
    FROM (
        SELECT team_id, uuid, 1 AS is_fe, 0 AS is_ev
        FROM flag_evaluations
        WHERE team_id IN ({{team_ids}}) AND toDate(timestamp) = '{{day}}'

        UNION ALL

        SELECT team_id, uuid, 0 AS is_fe, 1 AS is_ev
        FROM events
        WHERE team_id IN ({{team_ids}}) AND toDate(timestamp) = '{{day}}'
          AND event = '$feature_flag_called'
          -- The fork writes a row only when $feature_flag is a non-empty JSON
          -- string, and lets every other $feature_flag_called event through to
          -- the events table untouched. Without the same condition here, each
          -- one reads as a lost row.
          AND JSONType(properties, '$feature_flag') = 'String'
          AND JSONExtractString(properties, '$feature_flag') != ''
    )
    GROUP BY team_id, uuid
)
GROUP BY team_id
SETTINGS max_execution_time = 600,
         max_memory_usage = 107374182400,
         distributed_aggregation_memory_efficient = 1
```

A team with no rows on the day produces no result row at all. Compare the returned team ids against the ids you passed rather than assuming the result covers all of them.

## Reading the result

**`only_in_events` is a deficit.** The events table has a uuid the fork never wrote. This is the failure the check exists for, and it blocks widening. Deficit has measured zero on every day checked that was not a team's activation day, so treat any non-zero value as real rather than as noise. Walk the four items in the next section before chasing it, because three of them produce a false deficit.

**`only_in_flag_evaluations` is an excess.** The fork wrote a uuid the events table has no row for, which is loss on the events side. It has been small and non-zero on some days and zero on others. It is not explained yet, and on its own it does not block widening. Raise it if it grows.

**`in_both` is the covered population.** Use it as the denominator when judging whether either of the other two columns is large enough to matter.

## What makes the numbers wrong

### `JSONType` has to reject a numeric `$feature_flag`

`JSONExtractString(properties, '$feature_flag')` renders a number, boolean, object, or array as its text, so a `$feature_flag` of `123` returns `'123'` and passes an empty-string check. The fork writes only for a genuine JSON string. Drop the `JSONType(...) = 'String'` line and every event with a non-string `$feature_flag` reads as a lost row.

### Group by `(team_id, uuid)` before counting

`flag_evaluations` is a plain MergeTree and keeps the duplicate rows a Kafka replay produces. The ReplacingMergeTree behind events collapses them. Counting rows per side instead of distinct uuids reports that difference in table engine as a parity failure.

Grouping first also means a re-sent uuid that reached both tables lands in `in_both`, not in the excess column.

### Keep the memory and time ceilings on the query

This runs on the cluster that serves customer queries. The group-by state grows with a whole day of `$feature_flag_called` uuids for the largest team in the batch, and `distributed_aggregation_memory_efficient` is what streams each shard's states instead of merging them all in the initiator.

If a batch reaches a ceiling, shrink the batch. Do not raise the ceiling.

### Delayed lanes never fork

The fork runs only on the real-time lanes, and that is enforced in code rather than left to deployment config. `createFlagEvaluationsService` in `nodejs/src/ingestion/common/flag-evaluations/flag-evaluations-service.ts` returns `undefined` for any lane outside `REALTIME_INGESTION_LANES`, and the pipeline composes the fork step out entirely when it does. Setting the env vars on the `historical` or `async` lane does not switch it on. The reason for the gate is that a backfill owns this table's history, so a delayed lane that also forked would write rows the backfill already covers.

The deficit this produces is therefore narrow. It is not a lane that should have forked and didn't. It is an event that arrives on a real-time lane, gets rerouted to a delayed lane, and reaches the events table with no fork row, which reads as a deficit for a team whose fork is healthy.

Check it first on a deficit that names a team with no other sign of trouble.

## Why this is not a scheduled job

An always-on Dagster version was built and closed unmerged in [PR #92749](https://github.com/PostHog/posthog/pull/92749). It needed three things a hand-run check does not: a source of truth for which teams are enabled, a rule for what catch-up ticks after an outage should do, and a threshold for excess.

Revisit it once the allowlist reaches `*`. At that point "which teams are enabled" stops being a question, and the first of those three problems goes away.
