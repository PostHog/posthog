# Snapshot materialization

Status: implemented behind the snapshot configuration contract. This document records the approved
observation-time SCD type 2 design and the first implementation boundaries.

## Contract

A snapshot records changes observed in the complete result of a saved query at each successful run.
It creates an SCD type 2 history table with observation-time validity intervals. Changes between
observations are outside the contract. History starts at the first successful observation; an
existing current-state materialization cannot provide earlier versions.

Snapshot is a third materialization mode alongside full refresh and incremental. Version 1 reads
the complete result on every run. The configured entity key must be present, non-null, and unique
across the complete result. Composite keys are supported. An empty result with a known schema is
valid.

The output contains the query columns and `valid_from`, `valid_to`, and
`_ph_snapshot_version_id`. `valid_from` is inclusive and `valid_to` is exclusive. Timestamps are
UTC with microsecond precision. The version identifier is derived from the history generation,
entity key, and logical run ID. Reserved output names are rejected.

Values are compared with null-safe, typed normalization. Nested mappings are compared independent
of key order. Timestamps, decimals, NaN, infinity, and nested values have deterministic forms.
Unsupported values and duplicate or null keys fail before a candidate is written.

| Compared with the current open version | Action |
| --- | --- |
| New entity | Insert an open version |
| Changed non-key value | Close the old version and insert an open version |
| Unchanged values | Preserve the existing version |
| Entity missing from the complete result | Close its open version |
| Entity returns after being absent | Insert a new version |

## Configuration and lifecycle

Saved queries accept the additive field:

```json
{"snapshot": {"unique_key": ["customer_id"]}}
```

`snapshot: null` disables snapshot mode before history exists. Snapshot and enabled incremental
configuration are mutually exclusive. Once snapshot history exists, changing or removing its
configuration is rejected with guidance to create another model. Readers expose the effective
mode as `full_refresh`, `incremental`, or `snapshot`.

Snapshot state is separate from incremental state. It records the committed generation URI,
observation timestamps, logical run ID, query-result counts, and the latest observation statistics.
The saved query remains scheduled by the existing DAG and does not depend on demand.

## Run and publication protocol

The implementation uses an immutable candidate generation. The current Delta path is never deleted
by a snapshot run. A run reads the complete query into an attempt-specific candidate, applies the
comparison policy to the last committed generation, writes the complete candidate to a dedicated
snapshot-generation path, and passes that exact file list to the existing queryable-table staging
activity. Snapshot state is updated only with the queryable publication update.

Existing full-refresh and incremental paths remain unchanged. In particular, snapshots do not call
the destructive full-refresh helper. A failed extraction or candidate build leaves the committed
generation and queryable table untouched. A failed publication can retry the same logical run and
candidate. The persisted generation URI prevents the next successful run from reading an
unpublished candidate.

The first implementation uses the existing batch query producer and collects its Arrow rows before
candidate construction. This is intentionally bounded to the current scheduled snapshot scope;
disk-backed manifest comparison and persisted execution ownership are follow-up requirements before
large histories are enabled. The candidate path and exact file-list publication are retained so
those limits can be introduced without changing the history contract.

## Querying

Current rows use:

```sql
SELECT * FROM customer_history WHERE valid_to IS NULL
```

Rows at an observation boundary use:

```sql
SELECT *
FROM customer_history
WHERE valid_from <= :as_of
  AND (valid_to > :as_of OR valid_to IS NULL)
```

Between runs these queries return the last observed state, not a guarantee about the live source.

## CDC boundary

The existing CDC history path and `Scd2DeltaWriter` are not changed. CDC records source changes and
deletion metadata, while snapshots record only differences between complete scheduled observations
and close missing rows without tombstones. Shared validity column names do not make the contracts
interchangeable.

## Validation evidence

The implementation was validated against the existing Delta writer, explicit file-list queryable
staging, and the saved-query publication update. Regression coverage exercises initial and unchanged
observations, updates, disappearance and reappearance, composite keys, duplicate and null keys,
reserved columns, nested values, null-safe comparison, and column-order independence.

Before production rollout, measure candidate rewrite and queryable-file copy costs at representative
history sizes, add persisted ownership and stale-worker publication checks, and add failure-injection
coverage for extraction, candidate writing, staging, publication acknowledgment, overlapping runs,
schema drift, and generic rebuild attempts. Keep rollout behind a feature flag until those checks
are complete.
