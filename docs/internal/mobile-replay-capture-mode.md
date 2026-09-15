# Mobile replay capture mode

Replay ingestion sends `snapshot_mode` in its Kafka metadata payload.
The materialized view stores that value as a nullable string aggregate state in `snapshot_mode_v2`, so recordings can be counted by rendering mode without downloading replay blobs.
This field only applies to events with `$snapshot_source = 'mobile'`.
The aggregate table stores capture mode only in `snapshot_mode_v2`.

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
ClickHouse stores `AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))` and retains the first non-null mode across blocks.
The materialized views and destination tables use matching plain nullable aggregate states for `snapshot_source`, `snapshot_library`, and `snapshot_mode_v2`.
Blocks without visual evidence cannot overwrite a known mode.

## Querying daily recording counts

Use `argMinMerge(snapshot_mode_v2)` on the physical ClickHouse `session_replay_events` table.
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
        argMinMerge(snapshot_mode_v2) AS mode,
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

Existing installations need schema cleanup before deploying this change.
Coordinate with the ClickHouse team to remove the old stored `snapshot_mode` column and align `snapshot_source` to `AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))` on the sharded, writable, and read tables.
Migration `0322` checks these prerequisites on every target node before adding columns or replacing the materialized views.
If a check fails, the migration stops without changing tables or views.
Complete the coordinated cleanup, then retry the migration.
Changes to historical migrations apply to fresh installations and do not repair tables on installations that already ran them.
The replacement-column migration does not perform this cleanup or convert existing source aggregate states.

The replacement-column migration adds `snapshot_mode_v2` to the sharded, read, and writable tables before recreating the active MSK or WarpStream materialized view.
The producer's `snapshot_mode` payload and the Kafka table remain unchanged, so the ingestion classifier does not need a coordinated deployment.
Old producers can omit the nullable field during rollout.

The migration does not backfill `snapshot_mode_v2`.
Do not remove the Kafka payload field; it supplies `snapshot_mode_v2`.

Only blocks ingested through the updated materialized view populate `snapshot_mode_v2`.
Historical recordings remain unknown unless new blocks identify their mode or retained replay blobs are classified and backfilled separately.
The anonymized ML mirror uses separate metadata storage and is outside this ClickHouse reporting path.
