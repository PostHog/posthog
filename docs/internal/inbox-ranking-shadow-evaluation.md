# Inbox ranking shadow evaluation

The shadow job compares model, served and seeded random orders without changing what the inbox serves.
The served baseline pools all selected sorts because impression events do not record the sort.
Logged outcomes have position bias, so the comparison is not a causal estimate of a model rollout.

The read reconstructs complete lists from newly shown impression rows in five-second UTC windows.
It groups by viewer, session, scope and normalized tab, combines merged state sections and pagination by absolute rank, and requires every rank through the maximum list size.
Incomplete or conflicting windows are excluded; window boundaries can lose valid observations, and nearby visits can combine without a render ID.
Later visits outside the window remain separate.

Scores become available at the S3 object's `LastModified`, read with the score bytes.
Unscored reports retain their outcomes and go last in the model order.
Coverage is computed separately for each family, role and head.
A missing champion partition uses candidate scores as an explicit fallback, not as evidence of the historical champion pointer.

The daily job has a one-hour timeout.
Every completed evaluation emits `inbox_ranking_shadow_run_completed`, including runs with zero grades and a `reason`: `no_complete_lists`, `no_available_scores`, or `no_gradeable_outcomes`.
Per-order metrics remain on `inbox_ranking_shadow_ranking_graded`.
See the [ranking DAG README](../../products/signals/dags/inbox_ranking/README.md) for configuration and metric definitions.
