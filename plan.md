# Fix duplicate clustering signals — implementation plan

## Problem

The video segment clustering pipeline runs **every hour** over a **7-day lookback window** (`constants.py:13-14`).
Every run fetches all video segments from the past 7 days, clusters them with HDBSCAN/K-means, and emits a signal for each cluster.

The same stable pattern (e.g. "users confused by checkout flow") will be rediscovered on every run — the segments that form it persist in ClickHouse for the full 7 days.
Each run generates a new `workflow_id`, so the `source_id` (`{team_id}:{workflow_id}:{cluster_id}`) is different every time, and no deduplication happens.

The downstream `TeamSignalGroupingWorkflow` tries to semantically match the incoming signal to existing reports, but:
- The same description gets matched to the same report, inflating `signal_count` and `total_weight` by ~24× per day.
- The report re-promotes after the snooze gate (`signals_at_run + 3`) is quickly exceeded.
- The LLM matching + specificity check is repeated needlessly (~168 times/week for a stable pattern).

## Root cause

There is no mechanism to say "I already emitted a signal for this cluster of segments — skip it."
The `source_id` changes on every workflow run, and there's no content-hash or segment-set deduplication.

## Proposed fix: incremental clustering with segment-level tracking

### Core idea

Instead of re-clustering the entire 7-day window and blindly emitting signals, **track which segments have already been clustered** and only emit signals for genuinely new observations.

### Implementation

#### Option A — Segment-level "already clustered" tracking (recommended)

Add a **high-water mark** approach: after successfully emitting signals for a clustering run, record which `document_id`s were included.
On the next run, fetch *all* segments in the lookback window but **partition them** into "already seen" and "new" before clustering.

**Changes:**

1. **New ClickHouse table or metadata flag** — After a successful clustering run, mark segments as "clustered" by writing a lightweight record (team_id, document_id, clustered_at, cluster_label_hash) into either:
   - A new `clustered_segments` table (simplest), or
   - A metadata update on the existing `document_embeddings` row (more complex)

2. **Modified fetch activity** (`a2_fetch_segments.py`) — Add a LEFT ANTI JOIN (or NOT IN subquery) against the clustered-segments table so that only unclustered segments are returned.

3. **Modified emit activity** (`a4_emit_signals_from_clusters.py`) — After emitting signals, write the segment IDs to the clustered-segments table.

4. **Fallback for cluster evolution** — If a new segment joins an existing pattern, we want a new signal. The anti-join naturally handles this: the new segment is unclustered, gets fetched, and if it clusters with nothing else new, it either:
   - Gets labeled as a single-segment cluster (if below noise threshold) and emitted as a lightweight signal, or
   - Gets accumulated for the next run (if below `MIN_SEGMENTS_FOR_CLUSTERING`).

**Pros:**
- Clean separation: clustering only sees new material
- Naturally handles the "new occurrence of existing pattern" case
- No LLM cost for re-processing stable patterns
- Simple to reason about

**Cons:**
- Requires a new ClickHouse table (or column)
- Need to handle the cold-start case (first run after migration clusters everything)
- Need TTL on the clustered-segments records (match the 7-day lookback)

#### Option B — Content-hash deduplication at emission time

Keep clustering the full window, but deduplicate at emission time by hashing cluster content.

**Changes:**

1. **Stable cluster fingerprint** — After labeling a cluster, compute a fingerprint from the sorted `document_id`s of its member segments (or from the cluster centroid embedding).

2. **Dedup check before emit** — Query ClickHouse for signals with matching fingerprint emitted in the last lookback window. If found, skip emission.

3. **Partial overlap handling** — If a cluster's segment set has changed (some old segments + some new), emit a signal only for the delta.

**Pros:**
- Minimal structural changes (no new tables)
- Works without modifying the fetch path

**Cons:**
- Still pays the full clustering + LLM labeling cost every hour (just skips emission)
- Fingerprint stability is fragile — adding one segment changes the hash
- Doesn't reduce the core waste (re-clustering 168 hours of data every hour)

#### Option C — Sliding window with overlap detection

Reduce the lookback window to a shorter period (e.g. 2 hours with 1 hour overlap) and use embedding similarity to merge new clusters with previously emitted signals.

**Changes:**

1. Reduce `DEFAULT_LOOKBACK_WINDOW` to 2-3 hours
2. After clustering, compare each cluster's centroid against recently emitted signal embeddings
3. If cosine similarity > threshold, treat as "same pattern, new occurrence" and emit a lighter-weight signal (or skip)
4. If no match, emit as a new signal

**Pros:**
- Dramatically reduces data volume per run
- Natural "new occurrence" detection via embedding similarity

**Cons:**
- Patterns that only emerge over longer time horizons may be missed
- Centroid comparison can be noisy (especially with LLM-generated descriptions)
- Adds complexity to the emit activity

## Recommendation

**Option A** is the cleanest and addresses the problem at its source.
The key insight: segments don't change once written — so once you've clustered a segment and emitted a signal for its cluster, you never need to cluster that segment again.

### Detailed Option A implementation plan

#### Step 1: Track clustered segments

Create a simple record per (team_id, document_id) in object storage or ClickHouse after successful signal emission.
Using a ClickHouse table is cleanest since the segments already live there:

```sql
CREATE TABLE posthog_clustered_segments (
    team_id Int64,
    document_id String,
    cluster_run_id String,   -- workflow run ID
    clustered_at DateTime64(3, 'UTC'),
    _timestamp DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(_timestamp)
ORDER BY (team_id, document_id)
TTL clustered_at + INTERVAL 14 DAY  -- 2× lookback for safety
```

#### Step 2: Modify segment fetching

In `data.py:_fetch_video_segment_rows_paginated()`, add a NOT IN subquery:

```sql
AND document_id NOT IN (
    SELECT document_id
    FROM posthog_clustered_segments
    WHERE team_id = {team_id}
)
```

This ensures each clustering run only sees genuinely new segments.

#### Step 3: Record clustered segments after emission

In `a4_emit_signals_from_clusters.py`, after successfully emitting signals, batch-insert all segment `document_id`s into `posthog_clustered_segments`.

Also record **noise segment IDs** — segments that were fetched but assigned to noise should also be marked, so they aren't re-fetched. (They'll naturally age out via TTL if they never become part of a cluster.)

#### Step 4: Handle the minimum-segments gate

Currently, if fewer than `MIN_SEGMENTS_FOR_CLUSTERING` (3) new segments exist, the workflow skips clustering entirely. This is fine — those segments will be picked up in the next run since they won't be in the clustered-segments table yet.

#### Step 5: Reduce lookback window (optional optimization)

Once incremental tracking is in place, the 7-day window becomes a "catch-up" mechanism rather than the primary clustering window. Consider reducing it to 24-48 hours to reduce ClickHouse query cost, since most segments will be filtered out by the anti-join anyway.

### Migration path

1. Deploy the `posthog_clustered_segments` table
2. Deploy the modified fetch query (anti-join) — first run will still cluster everything (cold start), but subsequent runs will be incremental
3. Monitor signal emission rates — should drop dramatically after the first run
4. Optionally reduce lookback window once stable
