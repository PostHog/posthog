# Sync Person Distinct IDs Workflow

Temporal workflow to fix dangling persons in ClickHouse by syncing missing distinct IDs from PostgreSQL.

## Problem

Persons can exist in ClickHouse `person` table with `is_deleted = 0` but have no corresponding `person_distinct_id2` records. This can happen due to race conditions or incomplete data migrations.

### Orphan Categories

| Category            | Person in CH | Person in PG | DID in CH | DID in PG | Action                           |
| ------------------- | ------------ | ------------ | --------- | --------- | -------------------------------- |
| **Fixable**         | Yes          | Yes          | No        | Yes       | Sync DID to CH                   |
| **Truly orphaned**  | Yes          | Yes          | No        | No        | Report only                      |
| **CH-only orphans** | Yes          | No           | No        | N/A       | Mark as deleted in CH (optional) |

## Solution

This workflow:

1. Finds orphaned persons in ClickHouse (persons without distinct IDs)
2. Looks up their distinct IDs in PostgreSQL
3. Syncs missing `person_distinct_id2` records to ClickHouse via Kafka
4. Optionally marks CH-only orphans (no PG data) as deleted in ClickHouse

## Workflow Inputs

```python
@dataclasses.dataclass
class SyncPersonDistinctIdsWorkflowInputs:
    team_id: int
    batch_size: int = 100
    dry_run: bool = True  # Safe by default
    delete_ch_only_orphans: bool = False  # If True, mark CH-only orphans as deleted (requires categorize_orphans=True)
    categorize_orphans: bool = False  # If True, run extra query to distinguish truly orphaned vs CH-only
    limit: int | None = None  # Max persons to process (for testing)
    person_ids: list[str] | None = None  # Specific person UUIDs to process (for testing)
```

## Workflow Result

```python
@dataclasses.dataclass
class SyncPersonDistinctIdsWorkflowResult:
    team_id: int
    total_orphaned_persons: int
    persons_with_pg_distinct_ids: int  # Fixable - have DIDs in PG
    distinct_ids_synced: int
    persons_without_pg_data: int  # Truly orphaned + CH-only combined
    persons_truly_orphaned: int  # In PG but no DIDs (only if categorize_orphans=True)
    persons_ch_only: int  # Not in PG at all (only if categorize_orphans=True)
    persons_marked_deleted: int  # Only if delete_ch_only_orphans=True and dry_run=False
    dry_run: bool
```

**Note:** When `categorize_orphans=True`, the workflow runs an extra query to distinguish between truly orphaned persons (exist in PG but have no DIDs) and CH-only orphans (don't exist in PG at all). This is useful for reporting but adds query overhead.

## Activities

| Activity                       | Purpose                                                      | Database    |
| ------------------------------ | ------------------------------------------------------------ | ----------- |
| `find_orphaned_persons`        | Query CH for all persons without distinct IDs (single query) | ClickHouse  |
| `lookup_pg_distinct_ids`       | Find distinct IDs for person UUIDs                           | PostgreSQL  |
| `sync_distinct_ids_to_ch`      | Write missing distinct IDs via Kafka                         | Kafka -> CH |
| `mark_ch_only_orphans_deleted` | Set is_deleted=1 for persons without PG data                 | Kafka -> CH |

### Workflow Logic

1. **Single CH query** to get all orphaned person UUIDs (result set is small - just UUIDs)
2. **Batch processing** of PG lookups and CH writes (these are the expensive parts)

This avoids inefficient OFFSET pagination - instead of N queries each scanning O(n) rows, we do 1 query for discovery + batched processing.

## Behavior Matrix

| dry_run | delete_ch_only_orphans | Sync DIDs? | Mark orphans deleted? |
| ------- | ---------------------- | ---------- | --------------------- |
| true    | false                  | No (log)   | No                    |
| true    | true                   | No (log)   | No (log)              |
| false   | false                  | **Yes**    | No                    |
| false   | true                   | **Yes**    | **Yes**               |

**Note:** `delete_ch_only_orphans=true` requires `categorize_orphans=true`. This ensures we only delete persons that are confirmed to be CH-only (not in PG at all), not truly orphaned persons (in PG but without DIDs).

## CLI Usage

```bash
# Dry run (default, safe) - reports what would be done
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2}'

# Dry run with limit - process only first 10 orphans (for testing)
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2, "limit": 10}'

# Dry run for specific persons (for testing)
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2, "person_ids": ["uuid-1", "uuid-2"]}'

# Dry run with delete_ch_only_orphans - shows what would be marked deleted too
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2, "delete_ch_only_orphans": true, "categorize_orphans": true}'

# Dry run with categorization - reports truly orphaned vs CH-only separately
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2, "categorize_orphans": true}'

# Production: sync only (don't mark CH-only orphans as deleted)
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2, "dry_run": false}' \
    --workflow-id "sync-person-distinct-ids-team-2"

# Production: sync AND mark CH-only orphans as deleted
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 2, "dry_run": false, "delete_ch_only_orphans": true, "categorize_orphans": true}' \
    --workflow-id "sync-person-distinct-ids-team-2"
```

## Key Queries

### Find orphaned persons (ClickHouse)

```sql
SELECT id AS person_id, team_id, created_at, version
FROM person FINAL
WHERE team_id = %(team_id)s
  AND is_deleted = 0
  AND id NOT IN (
    SELECT DISTINCT person_id FROM person_distinct_id2 FINAL
    WHERE team_id = %(team_id)s
  )
ORDER BY created_at ASC
LIMIT %(limit)s  -- optional
```

### Lookup distinct IDs (PostgreSQL)

```sql
SELECT p.uuid::text, pdi.distinct_id, COALESCE(pdi.version, 0)
FROM posthog_person p
JOIN posthog_persondistinctid pdi ON pdi.person_id = p.id
WHERE p.team_id = %(team_id)s
  AND p.uuid = ANY(%(person_uuids)s::uuid[])
```

## Local Testing

A management command is provided to create test orphan data for local development.

### Setup test data

```bash
# Create default test orphans (3 fixable, 2 truly orphaned, 2 CH-only)
python manage.py setup_orphan_test_data --team-id 1

# Create custom counts
python manage.py setup_orphan_test_data --team-id 1 \
    --fixable 5 \
    --truly-orphaned 3 \
    --ch-only 2

# Use custom prefix for distinct IDs
python manage.py setup_orphan_test_data --team-id 1 --prefix my-test
```

### Run the workflow

```bash
# Dry run - see what would be synced/deleted
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 1}'

# Actually sync fixable orphans
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 1, "dry_run": false}'

# Sync + mark CH-only orphans as deleted
python manage.py start_temporal_workflow sync-person-distinct-ids \
    '{"team_id": 1, "dry_run": false, "delete_ch_only_orphans": true, "categorize_orphans": true}'
```

### Verify results

```sql
-- Check for remaining orphans in ClickHouse
SELECT id, team_id, is_deleted, version
FROM person FINAL
WHERE team_id = 1
  AND is_deleted = 0
  AND id NOT IN (
    SELECT DISTINCT person_id FROM person_distinct_id2 FINAL WHERE team_id = 1
  );

-- Check synced distinct IDs
SELECT person_id, distinct_id, version, is_deleted
FROM person_distinct_id2 FINAL
WHERE team_id = 1
  AND distinct_id LIKE 'test-orphan%';
```

### Cleanup test data

```bash
python manage.py setup_orphan_test_data --team-id 1 --cleanup
```

### Test scenarios

| Scenario         | Command                                                                                          | Expected Result                              |
| ---------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| Dry run          | `'{"team_id": 1}'`                                                                               | Logs counts, no changes                      |
| Categorized      | `'{"team_id": 1, "categorize_orphans": true}'`                                                   | Reports truly orphaned vs CH-only separately |
| Sync only        | `'{"team_id": 1, "dry_run": false}'`                                                             | Fixable orphans get DIDs synced              |
| Sync + delete    | `'{"team_id": 1, "dry_run": false, "delete_ch_only_orphans": true, "categorize_orphans": true}'` | DIDs synced + CH-only marked deleted         |
| Limit            | `'{"team_id": 1, "limit": 2}'`                                                                   | Only process first 2 orphans                 |
| Specific persons | `'{"team_id": 1, "person_ids": ["uuid-1"]}'`                                                     | Only process specified UUIDs                 |

## Design Decisions

1. **Single team per workflow** - Run separate instances for different teams (simpler, better isolation)
2. **Batch size 100** - Balances throughput vs memory
3. **Idempotent** - `person_distinct_id2` uses `ReplacingMergeTree` with version dedup
4. **Dry run by default** - Safe; logs what would happen without making changes
5. **Mark CH-only orphans deleted opt-in** - Destructive action requires explicit flag
6. **Categorization opt-in** - Extra query to distinguish truly orphaned vs CH-only; off by default to avoid overhead
7. **Heartbeating** - All activities use `Heartbeater` for long operations
8. **Persons database** - Uses `PERSONS_DB_READER_URL` for PostgreSQL queries (persons tables are in a separate database)
9. **Per-distinct-ID versions** - Each distinct ID has its own version (not per-person), preserved when syncing to ClickHouse
10. **Version-aware deletion** - Uses `current_version + 1` when marking persons as deleted to ensure ClickHouse's ReplacingMergeTree picks up the deletion
