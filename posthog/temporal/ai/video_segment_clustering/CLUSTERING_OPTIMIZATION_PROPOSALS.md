# Video Segment Clustering: Optimization Proposals

## Problem Statement

The current `fetch_segments_activity` downloads up to 50,000 video segments from ClickHouse,
each carrying a 3072-dimensional Float64 embedding vector.
This produces **~600 MB–1.2 GB** of data transfer per clustering run.

**Math:** 50k segments × 3072 floats × 8 bytes/float = **~1.2 GB of embeddings alone**,
plus `content`, `metadata`, and `document_id` per row.

The pipeline runs **hourly** with a **7-day lookback**, meaning ~85% of segments
from the last run are re-fetched and re-clustered every hour.

## Current Architecture

```text
ClickHouse (document_embeddings)
    │
    ▼  [600MB+ over network, paginated 5k/page]
Temporal Activity (fetch_segments)
    │
    ▼  [gzip JSON to S3]
Object Storage (S3)
    │
    ▼  [load into memory]
Temporal Activity (cluster_segments)
    │  sklearn KMeans / AgglomerativeClustering in-memory
    ▼
Temporal Activity (emit_signals)
    │  LLM label per cluster → emit_signal()
    ▼
Signal Grouping Workflow
```

---

## Proposal 1: Incremental Clustering with Persistent Centroids

**Core idea:** Don't re-cluster everything from scratch every hour.
Maintain cluster centroids across runs and only process _new_ segments.

### How it works

1. After each clustering run, persist the finalized centroids
   (cluster_id → centroid vector + metadata) to Postgres or a dedicated ClickHouse table.
2. On the next run, for each _new_ segment (inserted since last run),
   query ClickHouse to compute `cosineDistance(embedding, <centroid>)` against all known centroids.
   This can use the HNSW vector index.
3. If a segment is within threshold of an existing centroid → assign it; no embedding download needed.
4. Only download unassigned segments for new cluster formation.

### Data transfer reduction

If 200 new segments appear per hour and 90% match existing centroids:

- Before: 50,000 × 24 KB = **~1.2 GB**
- After: ~20 unmatched × 24 KB = **~0.5 MB** + N centroid-distance SQL queries

### Implementation sketch

```python
# New: assign_to_existing_clusters_activity
# Runs BEFORE fetch_segments. For each centroid, find segments within threshold.

def assign_new_segments_to_existing_clusters(
    team: Team,
    centroids: list[tuple[int, list[float]]],  # (cluster_id, centroid_vector)
    since_timestamp: datetime,
    distance_threshold: float = 0.4,
) -> tuple[dict[str, int], list[str]]:
    """
    Returns:
        assigned: {document_id: cluster_id} for segments matching an existing centroid
        unassigned_ids: document_ids that need full clustering
    """
    # For each centroid, run an ANN query in ClickHouse:
    # SELECT document_id, cosineDistance(embedding, <centroid>) as dist
    # FROM document_embeddings
    # WHERE timestamp >= <since> AND dist < <threshold>
    # ORDER BY dist LIMIT 1000
    ...
```

### Trade-offs

- **Pro:** Dramatic data transfer reduction (orders of magnitude)
- **Pro:** Leverages existing HNSW indexes
- **Pro:** Centroids naturally evolve as new segments shift the mean
- **Con:** Requires persisting centroid state (Postgres column or ClickHouse table)
- **Con:** "Concept drift" — centroids may become stale; need periodic full re-clustering
- **Con:** New segments can only join existing clusters, not cause merges/splits
- **Mitigation:** Full re-cluster weekly; incremental hourly

---

## Proposal 2: Server-Side K-Means via Iterative SQL

**Core idea:** Run K-means iterations entirely within ClickHouse.
Never download embedding vectors at all.

### How it works

ClickHouse supports element-wise array operations and aggregations.
We can express K-means assignment + centroid update as SQL:

```sql
-- Step 0: Initialize centroids (random sample)
SELECT document_id, embedding
FROM document_embeddings
WHERE <filters>
ORDER BY rand()
LIMIT {k}

-- Step 1: Assign each segment to nearest centroid
SELECT
    d.document_id,
    arrayMin(
        arrayMap(
            (c_id, c_emb) -> (c_id, cosineDistance(d.embedding, c_emb)),
            centroids_ids, centroids_embeddings
        )
    ).1 as cluster_id
FROM document_embeddings d
WHERE <filters>

-- Step 2: Recompute centroids
-- ClickHouse doesn't have native array-of-array AVG,
-- but we can use arrayMap + groupArray tricks:
SELECT
    cluster_id,
    arrayMap(
        i -> avg(embedding[i]),
        range(1, 3073)  -- 1-indexed in CH
    ) as new_centroid
FROM assigned_segments
GROUP BY cluster_id
```

**Problem:** The cross-join in step 1 is O(n × k) distance computations per iteration,
all server-side. For 50k segments × 200 clusters × 10 iterations = 100M distance computations.
This is CPU-heavy but avoids network transfer entirely.

### Practical variant: ClickHouse as assignment oracle

Instead of full K-means in SQL, use a hybrid:

1. **Initialize centroids** client-side (download K random embeddings — tiny transfer)
2. **Assign segments** via ClickHouse SQL (insert centroid vectors as query parameters)
3. **Recompute centroids** via ClickHouse `GROUP BY` with array aggregation
4. **Iterate** steps 2–3 until convergence
5. **Download** final assignments only (cluster labels, no embeddings)

The centroid vectors (K × 3072 floats) are small enough to pass as query parameters.
The per-segment embeddings never leave ClickHouse.

### Data transfer

- Before: **~1.2 GB** (all embeddings)
- After: **~200 centroids × 24 KB × 10 iterations ≈ 48 MB** sent as query params,
  plus **~50k × 8 bytes ≈ 400 KB** of cluster assignments returned.
  Effectively **< 50 MB total** and most of it is upstream (centroids sent).

### Implementation sketch

```python
def _run_kmeans_iteration_in_clickhouse(
    team: Team,
    centroids: np.ndarray,  # shape (k, 3072)
    lookback_hours: int,
) -> tuple[dict[str, int], np.ndarray]:
    """
    Single K-means iteration executed server-side.
    Returns (assignments, new_centroids).
    """
    # Build a CTE or VALUES clause with centroid vectors
    # Then join against document_embeddings and find argmin cosineDistance
    query = """
    WITH centroids AS (
        SELECT
            arrayJoin(
                [{centroid_tuples}]
            ) AS (cluster_id, centroid_vec)
    )
    SELECT
        d.document_id,
        argMin(c.cluster_id, cosineDistance(d.embedding, c.centroid_vec)) AS best_cluster
    FROM document_embeddings d
    CROSS JOIN centroids c
    WHERE <standard_filters>
    GROUP BY d.document_id
    """
    # For centroid recomputation:
    recompute_query = """
    SELECT
        assigned_cluster,
        arrayMap(i -> avg(embedding[i]), range(1, 3073)) AS new_centroid
    FROM (
        <assignment subquery>
    )
    GROUP BY assigned_cluster
    """
```

### Trade-offs

- **Pro:** Zero embedding data leaves ClickHouse
- **Pro:** Leverages ClickHouse's columnar scan speed
- **Pro:** Algorithm is identical to current approach, just executed differently
- **Con:** K × 3072 centroid arrays as query parameters is unusual; need to test CH limits
- **Con:** Cross-join for assignment is O(n × k) — may be slow for large k
- **Con:** ClickHouse CPU load increases (but it's built for this)
- **Con:** Array aggregation for centroid recomputation may be slow for 3072-dim arrays

---

## Proposal 3: Dimensionality Reduction (Quick Win)

**Core idea:** Reduce the embedding dimension before clustering.
The full 3072 dims are needed for fine-grained similarity search,
but clustering only needs enough to separate groups.

### Option A: Use a smaller embedding model for clustering

Store a second, lower-dimensional embedding alongside the full one.
E.g. `text-embedding-3-small-1536` or even a 256-dim model.

- 50k × 256 × 8 = **~100 MB** (5× reduction from 256-dim)
- 50k × 1536 × 8 = **~614 MB** (2× reduction from 1536-dim)
- Already have `text-embedding-3-small-1536` table infrastructure

### Option B: Store Float32 instead of Float64

The embeddings are stored as `Array(Float64)` but clustering doesn't need
64-bit precision. Using Float32 halves the data:

- 50k × 3072 × 4 = **~600 MB** (2× reduction)

This requires a schema change but is trivially compatible with sklearn.

### Option C: Random projection at query time

ClickHouse can compute a random projection in the query:

```sql
SELECT
    document_id, content, metadata,
    arrayMap(
        i -> arraySum(arrayMap(j -> embedding[j] * projection_matrix[i][j], range(1, 3073))),
        range(1, 257)
    ) as reduced_embedding
FROM document_embeddings
WHERE <filters>
```

This is compute-heavy in CH but reduces transfer to 256 dims.
The projection matrix must be fixed across runs for consistency.

### Trade-offs

- **Pro:** Simplest change; clustering code barely changes
- **Pro:** Option B is nearly free to implement
- **Con:** Still downloads all segment data, just smaller vectors
- **Con:** Dimensionality reduction may hurt cluster quality (needs testing)
- **Con:** Option A doubles embedding API costs

---

## Proposal 4: ClickHouse-Side Approximate Clustering via Leader-Follower

**Core idea:** Use ClickHouse's nearest-neighbor capabilities to build
approximate clusters without downloading any embeddings.

### How it works

1. **Pick seed points:** Sample N random segments as initial cluster leaders
2. **Assign followers:** For each leader, use ClickHouse's HNSW index
   to find all segments within `cosineDistance < threshold`
3. **Mark assigned segments** so they're excluded from future leader picks
4. **Repeat** until all segments are assigned or remaining are noise

This is a "leader-follower" / "canopy clustering" algorithm.
It produces approximate clusters in O(N × log(total)) time via ANN indexes.

```sql
-- For each leader embedding, find followers:
SELECT document_id, cosineDistance(embedding, {leader_embedding}) as dist
FROM document_embeddings
WHERE <filters>
    AND document_id NOT IN ({already_assigned})
ORDER BY dist ASC
LIMIT 500  -- cap cluster size
HAVING dist < 0.4  -- distance threshold
```

### Data transfer

- Download K leader embeddings (K × 24 KB ≈ tiny)
- Run K ANN queries returning only document_ids + distances
- Download `content` + `metadata` only for cluster members (no embeddings)
- Total: **< 10 MB** for reasonable cluster counts

### Trade-offs

- **Pro:** Uses existing HNSW indexes (already built for cosine distance)
- **Pro:** Very low data transfer
- **Pro:** Naturally parallelizable (one query per leader)
- **Con:** Cluster quality depends on leader selection (random may miss good seeds)
- **Con:** Not identical to K-means; produces different cluster shapes
- **Con:** Sequential dependency: need to track "already assigned" across queries

---

## Proposal 5: Hybrid — Coarse ClickHouse Grouping + Fine Client-Side Refinement

**Core idea:** Two phases. Phase 1 does rough grouping in ClickHouse
(zero embedding transfer). Phase 2 only downloads embeddings for
ambiguous border cases.

### Phase 1: ClickHouse-side coarse grouping

Use Proposal 2 or 4 to assign most segments to coarse clusters server-side.
Output: `(document_id, coarse_cluster_id)` for all segments.

### Phase 2: Client-side refinement (only if needed)

For clusters that are too large or have high intra-cluster variance:

- Download only those clusters' embeddings
- Split/merge as needed using the existing sklearn logic
- Typically affects <10% of segments

### Data transfer

- Phase 1: ~0 (only cluster assignments returned)
- Phase 2: ~10% × 1.2 GB = **~120 MB** worst case, often much less

---

## Recommendation

**Start with Proposal 1 (incremental clustering)** as the highest-impact,
lowest-risk change:

1. The hourly schedule with 7-day lookback means ~85% of work is redundant.
   Persisting centroids and only processing new segments eliminates most transfer.
2. It doesn't change the clustering algorithm — same K-means/agglomerative logic,
   just applied to fewer segments.
3. Fallback to full re-clustering is trivial (just skip the incremental path).

**Then layer on Proposal 2 (server-side K-means)** for the periodic full re-clustering
runs, so even those don't need to download embeddings.

**Quick wins to do immediately:**

- Switch embeddings from Float64 to Float32 (Proposal 3B) — 50% reduction for free
- Track `last_clustered_at` timestamp per team to enable incremental fetching

### Effort estimates

| Proposal                    | Data reduction | Effort   | Risk     |
| --------------------------- | -------------- | -------- | -------- |
| 1. Incremental clustering   | 95%+           | Medium   | Low      |
| 2. Server-side K-means      | 99%+           | High     | Medium   |
| 3A. Smaller embedding model | 50-90%         | Low      | Low      |
| 3B. Float32 embeddings      | 50%            | Very low | Very low |
| 4. Leader-follower in CH    | 99%+           | Medium   | Medium   |
| 5. Hybrid coarse+fine       | 90%+           | High     | Low      |
