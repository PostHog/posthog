# Video segment clustering

This module automatically identifies recurring issues from session replay video analysis by clustering similar video segment descriptions and creating Tasks for engineering teams to investigate.

## What is this?

Session replays are analyzed by AI to generate natural language descriptions of what users are doing in each video segment. These descriptions are embedded as vectors and stored in ClickHouse. This workflow periodically processes those embeddings to find patterns - if multiple users encounter the same issue (e.g., "User clicked submit button repeatedly but nothing happened"), those segments cluster together and become a Task for the team to fix.

The end result: recurring user friction points surface automatically as prioritized Tasks, without anyone having to manually watch session replays.

## How it works

### Pipeline overview

```text
Video Segments (embeddings in ClickHouse)
    ↓
Fetch unprocessed segments
    ↓
HDBSCAN clustering (with PCA: 3072 → 100 dims)
    ↓
    ├── Clusters (2+ segments)
    └── High-impact noise (single segments worth tracking)
            ↓
    Match to existing Tasks (by centroid cosine distance)
            ↓
    ├── New clusters → LLM label → Create Task
    └── Matched clusters → Update existing Task
            ↓
    Link segments to Tasks, update watermark
```

### Key components

| File             | Purpose                                                          |
| ---------------- | ---------------------------------------------------------------- |
| `workflow.py`    | Orchestrates the per-team clustering pipeline                    |
| `coordinator.py` | Discovers enabled teams via feature flag, spawns child workflows |
| `clustering.py`  | HDBSCAN clustering with PCA dimensionality reduction             |
| `labeling.py`    | LLM-based label generation for new clusters                      |
| `priority.py`    | Calculates Task priority from impact, user count, recency        |
| `data.py`        | HogQL queries for fetching segment embeddings                    |
| `activities.py`  | Temporal activities wrapping each step                           |
| `models.py`      | Data classes for workflow inputs/outputs                         |
| `constants.py`   | Configuration: thresholds, timeouts, weights                     |
| `schedule.py`    | Temporal schedule (runs every 30 minutes)                        |

### Workflow steps

1. **Fetch** - Query `document_embeddings` for video segments not yet processed (tracked by watermark)
2. **Cluster** - HDBSCAN groups similar embeddings; PCA reduces 3072 dims to 100 for efficiency
3. **Handle high-impact noise** - Segments that didn't cluster but have high impact (errors, confusion) get individual Tasks
4. **Match** - Compare cluster centroids to existing Task centroids; if cosine distance < 0.3, it's the same issue
5. **Label** - LLM generates actionable titles/descriptions for new clusters
6. **Create/Update Tasks** - New clusters become new Tasks; matched clusters update existing Task metrics
7. **Link** - Create `TaskSegmentLink` records and update the watermark for incremental processing

## Philosophy

### Automatic issue detection

Engineers shouldn't have to watch session replays to find bugs. If users are hitting the same issue repeatedly, the system should surface it automatically. The clustering approach finds these patterns without requiring explicit bug reports.

### Deduplication over noise

We'd rather have one well-documented Task with 50 linked segments than 50 separate Tasks. The centroid matching ensures that recurring issues consolidate into a single Task, whose priority grows as more users encounter it.

### Impact-aware prioritization

Not all issues are equal. A confusing flow that 100 users navigated successfully is less urgent than an error that blocked 5 users. Priority is calculated from:

- **User count** (log-scaled to prevent outliers dominating)
- **Impact score** (failure: 0.4, confusion: 0.3, abandonment: 0.2)
- **Recency** (exponential decay with 7-day half-life)

### High-impact noise handling

HDBSCAN marks some segments as "noise" (didn't fit any cluster). For most noise, this is correct - it's not a pattern. But if a noise segment has high impact (e.g., a crash), it deserves attention even without clustering. These become single-segment Tasks.

### Incremental processing

The workflow processes only new segments since the last run (tracked by `VideoSegmentClusteringState.last_processed_at`). This means:

- Each segment is processed exactly once
- Clusters can grow over time as new matching segments arrive
- No re-processing of historical data on every run

## Configuration

Key constants in `constants.py`:

| Constant                      | Value  | Purpose                                             |
| ----------------------------- | ------ | --------------------------------------------------- |
| `CLUSTERING_INTERVAL`         | 30 min | How often the coordinator runs                      |
| `MIN_CLUSTER_SIZE`            | 2      | Minimum segments to form a cluster                  |
| `TASK_MATCH_THRESHOLD`        | 0.3    | Max cosine distance to match existing Task          |
| `HIGH_IMPACT_NOISE_THRESHOLD` | 0.3    | Impact score above which noise gets individual Task |
| `PCA_COMPONENTS`              | 100    | Reduced dimensionality for clustering               |
| `RECENCY_HALF_LIFE_DAYS`      | 7      | Half-life for priority recency decay                |

## Rollout

Controlled via the `video-segment-clustering-enabled` feature flag. The coordinator queries for teams with this flag active and only processes those teams.

## Database models

The workflow creates/updates records in:

- `Task` - The issue to investigate (from `products/tasks`)
- `TaskSegmentLink` - Links individual segments to their Task
- `VideoSegmentClusteringState` - Watermark tracking per team
