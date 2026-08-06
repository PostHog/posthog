# Session surfacing scoring

Temporal pipeline that runs an XGBoost model over recently-created sessions and
writes the resulting surfacing score (a Float32 in `[0, 1]`) onto
`session_replay_events.surfacing_score`.

The score is intended to drive downstream session-summarization work — sessions
with higher scores are prioritized.

## Architecture

```text
Schedule (every 5 min, ScheduleOverlapPolicy.SKIP)
   │
   ▼
ScoreSessionsBatchWorkflow             (parent — scaffolding only)
   │
   ├── list_chunks_activity            (one cheap CH count, returns N specs)
   │
   └── asyncio.gather over chunks
         score_chunk_activity(spec)    (× N, runs in parallel)
            internally:
              1. CH SELECT eligible (hash-partitioned, IS NULL) sessions
                 from session_replay_events, INNER JOIN feature CTEs over
                 session_replay_features (same expressions as the
                 training query)
              2. validate_features (hard fail on schema drift)
              3. xgboost.Booster.predict
              4. get_producer(REPLAY) → Kafka topic
                 (clickhouse_session_replay_events)
              5. existing session_replay_events_mv merges the partial row
                 into the real session row in writable_session_replay_events
              6. return ChunkResult(scored=N)
```

### Score writeback path

Producer side (`activities._publish_scores`):

- One JSONEachRow message per scored session on
  `KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS` — the same topic ingestion uses.
- The payload carries `session_id`, `team_id`, `distinct_id`, an identity-value
  for every other column the Kafka table has, plus `surfacing_score`.
- `distinct_id` MUST be the session's real distinct_id — `writable_session_replay_events`
  shards on `sipHash64(distinct_id)`, so a wrong value would route the partial
  row to a different shard than the real session rows and the AggregatingMergeTree
  could never merge them. The eligible_sessions CTE surfaces it via `any(distinct_id)`.
- `first/last_timestamp = min_first_timestamp + 1µs` so min/max/argMin on
  the MV side keep the real session's values — using now() would shift
  max_last_timestamp forward by however long the scorer takes.
- `producer.flush(timeout=30s)` runs after the loop so the activity doesn't
  ack `scored=N` to the workflow before librdkafka has actually delivered.

Consumer side (no per-pipeline CH objects — we piggyback on ingestion):

- `kafka_session_replay_events` (Kafka engine) — already consumes from this topic.
- `session_replay_events_mv` aggregates with `GROUP BY session_id, team_id`
  and writes the `max(surfacing_score)` into the existing session row in
  `writable_session_replay_events`. Every identity-value column we sent merges
  as a no-op into the existing aggregates (sum of 0, max of NULL, etc.).

Identical pattern to the AI summarization writeback in
`posthog/temporal/session_replay/session_summary/activities/video_based/a7d_tag_and_highlight_session.py`.

### Two CH tables, one pipeline

- **`session_replay_events`** is where the score lives now (`surfacing_score`,
  `SimpleAggregateFunction(max, Nullable(Float32))`, write-once via the `IS NULL`
  filter on the read side and `max` on merge so a real score never gets clobbered
  by NULL). It sits alongside the existing AI-generated columns
  (`ai_tags_fixed`, `ai_tags_freeform`, `ai_highlighted`) — same write pattern.
- **`session_replay_features`** is where the model's input features live
  (the table populated by the replay feature pipeline). The pipeline keys
  on `(team_id, session_id)` with string `session_id`; the JOIN back to
  `session_replay_events` is a direct String-to-String match (no UUID
  byte-swap dance — that complexity disappeared when we moved off the
  `raw_sessions_v3.session_id_v7` UInt128 column).

The serving SELECT mirrors the training query verbatim: same
`aggregated_sufficient_statistics` and `replay_features` CTE shape, same
column names, same arithmetic — so any drift between training and serving
shows up as a `validate_features` failure rather than silent score skew.

### Feature schema sync (SQL ↔ FEATURE_RANGES ↔ booster)

The serving SQL and `FEATURE_RANGES` together define the **feature universe**;
they must stay identical (same columns, same order). The booster is the
source of truth for **which** of those features the model scores, and may use
a **subset** — a simpler model can run against the richer query without a
retrain or serving change.

| Artifact                                        | Source of truth for            | Relationship           |
| ----------------------------------------------- | ------------------------------ | ---------------------- |
| `fetch_features_sql()` final SELECT aliases     | What ClickHouse returns        | == `FEATURE_RANGES`    |
| `FEATURE_RANGES` keys in `features.py`          | Runtime dtype/range validation | == SQL aliases         |
| `booster.feature_names` in the S3-hosted `.ubj` | What XGBoost predicts on       | ⊆ the SQL / ranges set |

`feature_schema.py` enforces this:

- `assert_sql_matches_feature_ranges()` — SQL aliases **equal** `FEATURE_RANGES`
  keys (the universe is consistent).
- `assert_ranges_cover(booster)` / `assert_booster_matches_sql(booster)` — every
  booster feature is **in** the universe (subset). Extra universe columns the
  booster ignores are fine; `feature_matrix` selects the booster's by name, so
  serving column order is irrelevant to predictions.

Enforced at:

- **Worker boot**: `scorer.warmup()` fetches the booster from S3 and runs
  `assert_serving_schema_parity()` — a booster needing a column the SQL doesn't
  produce fails before accepting chunks.
- **CI** (`test_sql_alignment.py`): SQL ↔ FEATURE_RANGES equality, plus
  subset-booster parity (a proper-subset booster passes; one needing an
  unknown column fails).

To **extend** the universe: update `sql.py` SELECT + `FEATURE_RANGES` together,
bump `MODEL_FEATURE_SCHEMA_VERSION`, rerun the alignment tests. A new booster
that uses any subset of the universe deploys without further code changes —
just upload the `.ubj` (see [Uploading a model to S3](#uploading-a-model-to-s3)).

Sessions without replay features are dropped by the inner join and stay
NULL in `session_replay_events`. They re-appear on subsequent ticks until
they age out of the lookback window. That's deliberate — the model can't
score them, and writing a sentinel would either need a separate column or
break the write-once semantics. Keep the lookback tight so the wasted scan
cost is bounded.

### Why this shape

- **Workflow stays tiny** — no per-session work in workflow code, payloads stay
  far below the 2 MiB Temporal hard limit.
- **Hash partitioning** by `cityHash64(session_id) % of_chunks` gives every
  session exactly one bucket. Note this is a different key than the table's
  `sipHash64(distinct_id)` sharding key — the chunk fan-out only needs balanced
  buckets, not co-location with the data.
- **Idempotent on retry** — each chunk re-queries with
  `HAVING max(surfacing_score) IS NULL`, so a partial-failure retry
  naturally skips already-scored sessions. No claim/lock table needed.
- **No Redis, no S3** — every chunk is fetch-predict-write end-to-end inside
  one activity. Add Redis only if/when fetch and predict need to live on
  different worker pools (e.g., GPU vs CPU).
- **No dedicated Kafka triplet** — score writeback piggybacks on the existing
  replay ingestion topic + Kafka table + MV. We don't add a new Kafka topic,
  a new consumer group, or a new MV — the score is just another column written
  back via the same partial-row pattern as `ai_highlighted` and `is_deleted`.
  At-least-once delivery is harmless because the score column is
  `SimpleAggregateFunction(max, …)` and the pipeline only ever produces a
  single score per session.

## Throughput sizing

200k sessions / 5 min = ~667/sec. With XGBoost predict on tabular features,
the bottleneck is fetch + write, not score.

| chunk_size | of_chunks | concurrent on 2 workers | per-chunk wall time | tick wall time |
| ---------- | --------- | ----------------------- | ------------------- | -------------- |
| 5,000      | 40        | 4 in flight             | ~15s                | ~150s          |
| **10,000** | **20**    | **4 in flight**         | **~25s**            | **~125s**      |
| 20,000     | 10        | 4 in flight             | ~45s                | ~115s          |

Defaults in `constants.py` are `chunk_size=10_000`, `of_chunks=20`. Tweak
`TARGET_SESSIONS_PER_TICK` and `DEFAULT_OF_CHUNKS` for capacity changes.

## libomp thread budgeting

XGBoost on Linux uses `libgomp`; on macOS it uses `libomp`. Both are OpenMP
runtimes controlled by `OMP_NUM_THREADS`.

Surfacing scoring runs on the **session-replay worker** (the queue is aliased:
`SURFACING_SCORING_SWEEP_TASK_QUEUE = SESSION_REPLAY_TASK_QUEUE`), alongside the
worker's other replay work (LLM/CH/S3). XGBoost predict is the only OpenMP user
there, so the worker pins:

```bash
OMP_NUM_THREADS=1          # one thread per predict; parallelism comes from
MAX_CONCURRENT_ACTIVITIES=15   # concurrent activities, not libomp fan-out
```

`OMP_NUM_THREADS=1` stops libomp from fanning out × `MAX_CONCURRENT_ACTIVITIES`
and fighting the asyncio reactor / Temporal SDK threads for cores. Predict on
tabular features is cheap (the bottleneck is fetch + write, not score), so a
single predict thread is enough and doesn't starve the other replay activities.

### Containers + cgroups gotcha

`os.cpu_count()` returns the host's CPU count, not the pod's CPU limit — which is
why the chart sets `OMP_NUM_THREADS` explicitly rather than deriving it from
`nproc`.

## Model file

S3 is the **single source of truth** — no bundled fallback, no local-file
override. `SESSION_SURFACING_MODEL_S3_URI` (`s3://bucket/key`) is
required on every surfacing worker. Prod, staging, and local dev (against
MinIO) all use the same code path: fetch once per pod, cache to a
tempfile, roll pods to pick up new models.

Unset → `ModelNotConfiguredError` at worker boot. Warm with
`scorer.warmup()` so the S3 fetch isn't on the first chunk's path.

`xgboost==3.2.0` is a top-level dependency (pulls `nvidia-nccl-cu12`
~322 MB on Linux even in CPU mode) — deliberate trade-off for a single
worker image.

### Uploading a model to S3

```bash
./bin/python manage.py upload_surfacing_model ./surfacing_score_xgb_v1.ubj
# → s3://<settings.OBJECT_STORAGE_BUCKET>/surfacing-scoring/surfacing_score_xgb_v1.ubj

# Override bucket/key for versioned rollouts:
./bin/python manage.py upload_surfacing_model ./surfacing_score_xgb_v2.ubj \
    --bucket my-bucket --key surfacing-scoring/surfacing_score_xgb_v2.ubj
```

The command uses the same `posthog.storage.object_storage` client the
worker reads with (works against prod S3, staging, and local MinIO) and
validates the `.ubj` before upload (`--skip-validate` to bypass).

Then on the worker pod, roll to pick up the new model:

```bash
SESSION_SURFACING_MODEL_S3_URI=s3://<bucket>/surfacing-scoring/surfacing_score_xgb_v1.ubj
```

Plain `aws s3 cp` works too.

## Updating features

The trained XGBoost booster file is the **single source of truth** for which
features the model takes. `feature_names` is embedded inside the `.ubj` file
when training calls `xgb.DMatrix(..., feature_names=...)`, and serving reads
it back via `scorer.get_feature_names()`. A retrained booster with a
different feature set updates serving without a code change to `features.py`.

What still needs to be kept in sync **outside** the booster file:

1. `sql.fetch_features_sql` — the SELECT column list (plus the
   `_AGGREGATED_STATS_FRAGMENT` and `_REPLAY_FEATURES_FRAGMENT` CTEs that
   produce them) must produce a column named exactly the same as every
   `feature_names` entry, in the same order. `test_sql_alignment.py`
   asserts this at CI time; `validate_features` enforces it again at
   runtime as a defense in depth.
2. `features.FEATURE_RANGES` — runtime dtype + value-bounds contract.
   xgboost does **not** carry value ranges in the model file, so this is
   the runtime guard against "model trained on [0, 1] but the SQL started
   returning 9999". `assert_ranges_cover` runs inside `_load_booster` at
   warmup; any feature in the booster without a `FEATURE_RANGES` entry
   raises `MissingFeatureRangeError` before a single chunk is dispatched.
   `test_sql_alignment.py` also asserts equality (not just superset) so
   stale entries get flagged in CI too.

Workflow when changing features:

1. Update SQL (`_AGGREGATED_STATS_FRAGMENT`, `_REPLAY_FEATURES_FRAGMENT`,
   final SELECT) + `FEATURE_RANGES` to match.
2. Bump `features.MODEL_FEATURE_SCHEMA_VERSION`.
3. `pytest .../test_sql_alignment.py` passes when SQL and FEATURE_RANGES agree.
4. Retrain and upload the new `.ubj` (see [Uploading a model to
   S3](#uploading-a-model-to-s3)); roll workers. `assert_serving_schema_parity`
   fails boot loudly if the new booster's `feature_names` don't match.

`validate_features` is a hard gate — any mismatch raises
`FeatureValidationError`, marked `non_retryable=True` in the workflow so a
schema bug fails fast rather than burning retries.

## Schedule lifecycle

Singleton, region-scoped (one Schedule per Temporal cluster). Use
`schedule.a_upsert_schedule()` to register/update during deploy and
`schedule.a_delete_schedule_if_exists()` to retire it.

The schedule fires every 5 min with `ScheduleOverlapPolicy.SKIP` — if a tick
is still running when the next is due, the new one is dropped (the next
tick's CH `IS NULL` filter naturally picks up whatever the slow tick missed).

## Metrics

Temporal SDK metrics (Prometheus on the worker metrics port):

| Metric                                                     | Type      | When                                   |
| ---------------------------------------------------------- | --------- | -------------------------------------- |
| `surfacing_scoring_total_fetched`                          | counter   | end of each tick (`total_fetched > 0`) |
| `surfacing_scoring_total_scored`                           | counter   | end of each tick (`total_scored > 0`)  |
| `surfacing_scoring_chunks_failed`                          | counter   | end of each tick (`chunks_failed > 0`) |
| `surfacing_scoring_estimated_backlog`                      | gauge     | start of each tick (`list_chunks`)     |
| `surfacing_scoring_score_chunk_activity_execution_latency` | histogram | each `score_chunk_activity` run        |

`total_fetched` is rows the feature SELECT returned from ClickHouse;
`total_scored` is rows published to Kafka after dropping out-of-contract rows.
The gap between them is the out-of-contract drop; `total_fetched` near the
`TARGET_SESSIONS_PER_TICK` cap means the backlog exceeds one tick's budget and
will drain across several ticks.

Emitted via `SurfacingScoringMetricsInterceptor` on `SURFACING_SCORING_SWEEP_TASK_QUEUE`.

## Open follow-ups

These are deliberately out of scope for the initial PR:

- **Extend the feature set.** The initial production booster covers the
  36 features the live `session_replay_features` DDL exposes today. To add
  more (e.g. `*_path_visit_count`, `network_4xx_count`, `mutation_count`,
  `unique_form_field_count`), land them in
  `posthog/session_recordings/sql/session_replay_feature_sql.py` (CH
  migration + Kafka MV) first, then retrain + upload + update
  `sql.py`/`FEATURE_RANGES` (gated by `test_sql_alignment.py`).
- **Integration test for `score_chunk_activity`.** Unit coverage exists for
  `validate_features` and `scorer` (load + predict + thread safety + range
  guards). The end-to-end activity flow against real CH is still untested;
  start with a fixture-backed smoke test of `fetch_features_sql`.
- **Backfill.** Existing `session_replay_events` rows have NULL scores, which
  is fine for "score going forward". If we ever want to score historical
  sessions, write a one-off Dagster job that walks
  `cityHash64(session_id) % N` buckets and triggers the same
  `score_chunk_activity` per bucket.
