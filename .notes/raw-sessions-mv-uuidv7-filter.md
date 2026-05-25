# raw_sessions_mv silently drops non-UUIDv7 sessions

When session counts look mysteriously low (especially on dev or for legacy
data), check the `$session_id` UUID version first. The MV silently filters
on it.

## The filter

`posthog.raw_sessions_mv` reads from `sharded_events` and has this WHERE
clause baked in:

```sql
WHERE bitAnd(bitShiftRight(toUInt128(accurateCastOrNull(`$session_id`, 'UUID')), 76), 15) = 7
```

That extracts the UUID **version bits** (76-79) and only admits **UUIDv7**.
Anything else — UUIDv4, malformed, NULL after `accurateCastOrNull` — is
silently dropped at MV time. No error, no log, no warning.

## Why it exists

The MV is keyed on `session_id_v7` and uses `AggregatingMergeTree` to roll
all events for a session into ONE row (one row per session, not per hour —
the hour bucket in the GROUP BY is derived from the v7 timestamp in the UUID
itself, so it's constant per session). This rollup only works correctly when
the session ID encodes a sortable timestamp, i.e. UUIDv7.

`argMin/max/sum/uniq` aggregate states roll up new events into the existing
row via background merges, so a session spanning hours produces a single row
with `min_timestamp = first event`, `max_timestamp = last event`.

## How to diagnose on dev

```sql
SELECT bitAnd(bitShiftRight(toUInt128(accurateCastOrNull($session_id, 'UUID')), 76), 15) AS uuid_version,
       countDistinct($session_id) AS distinct_sessions,
       count() AS events
FROM posthog.events
WHERE team_id = <T> AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY uuid_version
ORDER BY events DESC
```

`version=7` rows are in raw_sessions. `version=None` rows (UUID parse
failed) and any other version are NOT.

## What this affects

Anything that joins events to `sessions` (the HogQL `session.*` virtual
columns) for session-level fields like `$entry_pathname`, `$is_bounce`,
`$start_timestamp`, etc. The web analytics raw query path AND the lazy
precompute INSERT both depend on it.

## What it does NOT mean

- "raw_sessions is out of date" — for UUIDv7 sessions it's current within
  MV merge latency (sub-second on prod, near-instant on dev).
- "We need a backfill" — non-v7 sessions are excluded by design; backfilling
  them would mean inserting non-v7 keys into a v7-keyed table.

## When it bites

- Local dev where fixtures or older toolbar code generated UUIDv4 session IDs.
- Synthetic/test events created via `_create_event` / `bulk_create_events`
  with handcrafted session IDs (use `uuid7()` from `posthog.models.utils`
  to be safe).
- Teams with historical data from before UUIDv7 became the SDK default.

## Reference

`posthog/clickhouse/raw_sessions_mv_sql.py` (or equivalent — search for the
`bitAnd(..., 15) = 7` filter).

Surfaced during PR #59665 debug session — INITIAL_PAGE lazy precompute
looked broken because of "missing" sessions; turned out the missing ones
were just UUIDv4.
