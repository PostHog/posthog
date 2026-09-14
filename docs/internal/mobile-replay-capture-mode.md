# Mobile replay capture mode

Replay ingestion stores `snapshot_mode` in ClickHouse recording metadata so recordings can be counted by rendering mode without downloading replay blobs.
This field only applies to events with `$snapshot_source = 'mobile'`.

## Classification

The first valid visual wireframe identifies the recording mode:

- `type = 'screenshot'`: `screenshot`.
- Any other or missing `type`: `wireframe`.
- No visual wireframe found: `NULL`.

A wireframe must be an object with a finite numeric `id`.
The classifier checks full snapshots at `data.wireframes` and incremental mutations at `data.adds[*].wireframe` and `data.updates[*].wireframe`.
It ignores metadata, touch, network, console, and removal-only events.
Base64 image data does not identify screenshot mode because wireframe-mode image views can also contain it.

A recording uses one mode throughout its lifetime.
The recorder stops inspecting wireframes once it identifies the mode for its in-memory storage block.
Each new block can identify the mode independently, without a shared cache or a ClickHouse lookup.
ClickHouse stores `AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC'))` and retains the first non-null mode across blocks.
Blocks without visual evidence cannot overwrite a known mode.

## Querying daily recording counts

Use `argMinMerge(snapshot_mode)` on the physical ClickHouse `session_replay_events` table.
The column is not exposed through the HogQL schema.
Group by both `team_id` and `session_id` before counting; one recording can have multiple rows or span midnight.

This example counts retained, non-deleted mobile recordings by their first recorded timestamp in UTC for one project.
Replace `1` with the project ID.
The date filter runs after session aggregation so a recording that crosses the reporting boundary keeps its original start date.

```sql
SELECT
    toDate(started_at, 'UTC') AS day,
    coalesce(mode, 'unknown') AS snapshot_mode,
    count() AS recordings
FROM
(
    SELECT
        team_id,
        session_id,
        min(min_first_timestamp) AS started_at,
        argMinMerge(snapshot_source) AS source,
        argMinMerge(snapshot_mode) AS mode,
        max(is_deleted) AS deleted
    FROM session_replay_events
    WHERE team_id = 1
    GROUP BY team_id, session_id
)
WHERE source = 'mobile'
    AND deleted = 0
    AND started_at >= toStartOfDay(now('UTC')) - INTERVAL 7 DAY
    AND started_at < toStartOfDay(now('UTC'))
GROUP BY day, snapshot_mode
ORDER BY day, snapshot_mode
```

This query scans retained metadata for the selected project.
For fleet-wide reporting, remove the project filter only after checking query cost.
Do not filter out null modes before aggregating sessions: that can move the apparent recording start to a later block.
Keep the `unknown` count visible to distinguish missing classifications from wireframe recordings.

## Deployment and historical data

Ship the ClickHouse migration separately and apply it before deploying the ingestion change.
The migration updates the sharded, read, and writable tables, plus the MSK or WarpStream ingestion path used by the environment.
Old producers can omit the nullable field during rollout.

Only newly ingested visual snapshots populate the mode.
Historical recordings remain unknown unless new blocks identify their mode or retained replay blobs are classified and backfilled separately.
The anonymized ML mirror uses separate metadata storage and is outside this ClickHouse reporting path.
