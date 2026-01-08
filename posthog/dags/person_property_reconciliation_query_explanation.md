# Person Property Reconciliation Query Explanation

This document explains the ClickHouse query in `get_person_property_updates_from_clickhouse` (person_property_reconciliation.py:98-211).

The query finds person properties that need reconciliation by comparing event-derived properties with current person state.

## Query Structure Overview

The query has 5 nested levels:

1. **Core Event Extraction** - Extract properties from events, resolve merged persons, aggregate per property
2. **Group into Arrays** - Collect all properties per person into one array
3. **Split by Operation Type** - Separate `$set` and `$set_once` into parallel arrays
4. **Join with Person State** - Get current person properties from ClickHouse
5. **Compute Diff** - Find properties that differ or are missing

---

## Level 1: Core Event Extraction with Person Resolution (Innermost)

```sql
SELECT
    if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id) AS person_id,
    kv_tuple.2 AS key,
    kv_tuple.1 AS prop_type,
    if(kv_tuple.1 = 'set',
        argMaxIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != ''),
        argMinIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != '')
    ) AS value,
    if(kv_tuple.1 = 'set', max(e.timestamp), min(e.timestamp)) AS kv_timestamp
FROM events e
LEFT OUTER JOIN (
    SELECT
        argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
        person_distinct_id_overrides.distinct_id AS distinct_id
    FROM person_distinct_id_overrides
    WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
    GROUP BY person_distinct_id_overrides.distinct_id
    HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
) AS overrides ON e.distinct_id = overrides.distinct_id
ARRAY JOIN
    arrayConcat(
        arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null',
            arrayMap(x -> tuple('set', x.1, toString(x.2)),
                arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set'))
            )
        ),
        arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null',
            arrayMap(x -> tuple('set_once', x.1, toString(x.2)),
                arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set_once'))
            )
        )
    ) AS kv_tuple
WHERE e.team_id = %(team_id)s
  AND e.timestamp > %(bug_window_start)s
  AND e.timestamp < %(bug_window_end)s
GROUP BY person_id, kv_tuple.2, kv_tuple.1
```

### The ARRAY JOIN

`ARRAY JOIN` "unrolls" an array into multiple rows. One input row becomes N output rows (one per array element).

The right side of the ARRAY JOIN builds an array of property tuples from each event:

```sql
arrayConcat(
    -- $set properties
    arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null',
        arrayMap(x -> tuple('set', x.1, toString(x.2)),
            arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set'))
        )
    ),
    -- $set_once properties (same structure)
    arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null',
        arrayMap(x -> tuple('set_once', x.1, toString(x.2)),
            arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set_once'))
        )
    )
) AS kv_tuple
```

Reading innermost to outermost (for the `$set` branch):

1. **`JSONExtractKeysAndValuesRaw(e.properties, '$set')`** - Extract `$set` object as `[(key, raw_json_value), ...]`
2. **`arrayFilter(x -> x.2 IS NOT NULL, ...)`** - Drop pairs where value is NULL
3. **`arrayMap(x -> tuple('set', x.1, toString(x.2)), ...)`** - Transform each `(key, value)` into `('set', key, value_string)`
4. **`arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null', ...)`** - Drop tuples where the string value is empty or literal `'null'`
5. **`arrayConcat(..., ...)`** - Combine `$set` and `$set_once` arrays into one

The resulting `kv_tuple` structure:

- `kv_tuple.1` = operation type (`'set'` or `'set_once'` - only these two values, hardcoded)
- `kv_tuple.2` = property key
- `kv_tuple.3` = property value (as JSON string)

Example: if an event has:

```json
{
  "$set": { "email": "a@b.com", "name": null },
  "$set_once": { "created": "2024-01-01" }
}
```

The result is:

```text
[('set', 'email', '"a@b.com"'), ('set_once', 'created', '"2024-01-01"')]
```

(The `name` property is filtered out because its value is null)

### The LEFT OUTER JOIN (Person Merge Resolution)

```sql
LEFT OUTER JOIN (
    SELECT
        argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
        person_distinct_id_overrides.distinct_id AS distinct_id
    FROM person_distinct_id_overrides
    WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
    GROUP BY person_distinct_id_overrides.distinct_id
    HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
) AS overrides ON e.distinct_id = overrides.distinct_id
```

This handles **person merges**. When two persons are merged, the `person_distinct_id_overrides` table records that a `distinct_id` now belongs to a different `person_id`.

The subquery:

1. **`GROUP BY distinct_id`** - One row per distinct_id
2. **`argMax(person_id, version)`** - Get the person_id from the row with the highest version (most recent assignment)
3. **`HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)`** - Only include overrides where the latest version is not deleted

The HAVING clause breakdown:

- `argMax(is_deleted, version)` - Get `is_deleted` value from row with highest version
- `equals(..., 0)` - Returns `1` if not deleted, `0` if deleted, `NULL` if NULL
- `ifNull(..., 0)` - Convert NULL to 0 (falsy), so NULL values get filtered out
- Result: `1` (truthy) keeps the row, `0` (falsy) filters it out

The join:

- `LEFT OUTER JOIN` keeps all events, even without an override
- Then: `if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id)` uses the override if it exists

### The SELECT Columns

Grouped by `(person_id, property_key, operation_type)`, producing one row per person per property per operation:

1. **`person_id`** - Use override if exists, else event's person_id
2. **`key`** - Property key (`kv_tuple.2`)
3. **`prop_type`** - `'set'` or `'set_once'` (`kv_tuple.1`)
4. **`value`** - The winning value:
   - For `$set`: `argMaxIf(value, timestamp, ...)` → value from the **latest** event
   - For `$set_once`: `argMinIf(value, timestamp, ...)` → value from the **earliest** event
   - The `If` suffix adds a condition: only consider rows where value is not null/empty
5. **`kv_timestamp`** - The timestamp of the winning event:
   - For `$set`: `max(timestamp)` → latest
   - For `$set_once`: `min(timestamp)` → earliest

This implements the semantics: `$set` overwrites (latest wins), `$set_once` only sets if not already set (first wins).

---

## Level 2: Group Properties into Arrays per Person

```sql
SELECT
    person_id,
    groupArray(tuple(key, value, kv_timestamp, prop_type)) AS grouped_props
FROM (... level 1 query ...)
GROUP BY person_id
```

**Input:** Multiple rows per person (one for each property/operation combo)

| person_id | key     | value        | kv_timestamp | prop_type |
| --------- | ------- | ------------ | ------------ | --------- |
| abc       | email   | "a@b.com"    | 2024-01-05   | set       |
| abc       | plan    | "pro"        | 2024-01-03   | set       |
| abc       | created | "2024-01-01" | 2024-01-01   | set_once  |
| xyz       | email   | "x@y.com"    | 2024-01-04   | set       |

**Output:** One row per person, all properties in an array of tuples

| person_id | grouped_props                                                                                                                          |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| abc       | [('email', '"a@b.com"', 2024-01-05, 'set'), ('plan', '"pro"', 2024-01-03, 'set'), ('created', '"2024-01-01"', 2024-01-01, 'set_once')] |
| xyz       | [('email', '"x@y.com"', 2024-01-04, 'set')]                                                                                            |

`groupArray()` is ClickHouse's aggregation function that collects all values in the group into an array.

---

## Level 3: Split Arrays by Operation Type

```sql
SELECT
    person_id,
    arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_keys,
    arrayMap(x -> x.2, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_values,
    arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_timestamps,
    arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_keys,
    arrayMap(x -> x.2, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_values,
    arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_timestamps
FROM (... level 2 query ...)
```

Separates `$set` and `$set_once` properties into parallel arrays (keys, values, timestamps) for easier comparison in the diff step.

---

## Level 4: Join with Current Person Properties

```sql
SELECT ...
FROM (...) AS merged
INNER JOIN (
    SELECT
        id,
        argMax(properties, version) as person_properties
    FROM person
    WHERE team_id = %(team_id)s
      AND _timestamp > %(bug_window_start)s
      AND _timestamp < %(bug_window_end)s
    GROUP BY id
) AS p ON p.id = merged.person_id
```

Gets the current person properties from ClickHouse's `person` table (using `argMax` to get the latest version).

---

## Level 5: Compute the Diff (Outermost)

```sql
SELECT
    with_person_props.person_id,
    -- For $set: only include properties where the key exists AND value differs
    arrayMap(i -> (set_keys[i], set_values[i], set_timestamps[i]), arrayFilter(
        i -> (
            indexOf(keys2, set_keys[i]) > 0
            AND set_values[i] != vals2[indexOf(keys2, set_keys[i])]
        ),
        arrayEnumerate(set_keys)
    )) AS set_diff,
    -- For $set_once: only include properties where the key does NOT exist
    arrayFilter(
        kv -> indexOf(keys2, kv.1) = 0,
        arrayMap(i -> (set_once_keys[i], set_once_values[i], set_once_timestamps[i]), arrayEnumerate(set_once_keys))
    ) AS set_once_diff
FROM (...) AS with_person_props
WHERE length(set_diff) > 0 OR length(set_once_diff) > 0
```

- **`set_diff`**: Properties from events where the value **differs** from current person properties
- **`set_once_diff`**: Properties from events that are **missing** from current person properties

Only returns persons where at least one property needs reconciliation.

---

## Summary

The query flows like this:

1. **Extract** `$set`/`$set_once` from events, resolving merged persons
2. **Aggregate** to find the winning value per property (latest for `$set`, first for `$set_once`)
3. **Group** all properties per person into arrays
4. **Join** with current person state from ClickHouse
5. **Diff** to find properties that need updating (different values for `$set`, missing keys for `$set_once`)

---

## Open Concerns (TODO: write tests)

### 1. Deleted/merged persons not filtered in person join

```sql
INNER JOIN (
    SELECT
        id,
        argMax(properties, version) as person_properties
    FROM person
    WHERE team_id = %(team_id)s
      AND _timestamp > %(bug_window_start)s
      AND _timestamp < %(bug_window_end)s
    GROUP BY id
) AS p ON p.id = merged.person_id
```

This doesn't filter out deleted persons (`is_deleted = 1`). What happens if a person was deleted or merged during the bug window? Could we be reconciling properties for a person that no longer exists?

### 2. Person state only from bug window - potential to overwrite newer updates

The person join only selects persons modified within the bug window (`_timestamp > bug_window_start AND _timestamp < bug_window_end`).

If a person received legitimate property updates **after** the bug window ended, will this reconciliation overwrite those newer updates with older values from the bug window?

The reconciliation logic in `reconcile_person_properties()` does compare timestamps via `properties_last_updated_at`, but need to verify this handles the edge case correctly.

---

## Future: Adding $unset Support

### Query changes

Add `$unset` extraction to the ARRAY JOIN (note: `$unset` is an array of keys, not key-value pairs):

```sql
-- In ARRAY JOIN arrayConcat:
arrayMap(x -> tuple('unset', x, ''),
    JSONExtractArrayRaw(e.properties, '$unset')
)
```

Add `unset_*` arrays in Level 3:

```sql
arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'unset', grouped_props)) AS unset_keys,
arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'unset', grouped_props)) AS unset_timestamps
```

Add `unset_diff` in Level 5 (keys where unset happened and key still exists):

```sql
arrayFilter(
    kv -> indexOf(keys2, kv.1) > 0,
    arrayMap(i -> (unset_keys[i], unset_timestamps[i]), arrayEnumerate(unset_keys))
) AS unset_diff
```

### Python resolution logic

Operation semantics:

- `$set_once`: "If not set, set it" - operation-level check, not a permanent property attribute
- `$set`: "Set it to this value" - always overwrites
- `$unset`: "Remove it" - always removes

Simulate applying operations in timestamp order:

```python
def resolve_property_updates(set_diff, set_once_diff, unset_diff):
    """
    Simulate applying operations in timestamp order.

    - set_once: sets value only if property is currently unset
    - set: always sets value
    - unset: always removes property
    """
    results_by_key = {}

    # Collect all operations by key
    ops_by_key = defaultdict(list)

    for key, value, ts in set_diff:
        ops_by_key[key].append(('set', value, ts))

    for key, value, ts in set_once_diff:
        ops_by_key[key].append(('set_once', value, ts))

    for key, ts in unset_diff:
        ops_by_key[key].append(('unset', None, ts))

    for key, ops in ops_by_key.items():
        # Sort by timestamp ascending
        ops.sort(key=lambda x: x[2])

        # Simulate applying each operation
        current_value = None  # None means unset
        current_ts = None

        for op_type, value, ts in ops:
            if op_type == 'set':
                current_value = value
                current_ts = ts
            elif op_type == 'set_once':
                if current_value is None:
                    current_value = value
                    current_ts = ts
                # else: ignore, property already has a value
            elif op_type == 'unset':
                current_value = None
                current_ts = ts

        results_by_key[key] = (current_value, current_ts)

    # Split into updates and deletions
    updates = {k: v for k, v in results_by_key.items() if v[0] is not None}
    deletions = {k for k, v in results_by_key.items() if v[0] is None}

    return updates, deletions
```

Example timeline for key `email`:

```text
t1: set_once "a@b.com"  → value = "a@b.com"
t2: set_once "x@y.com"  → ignored (already set)
t3: set "new@b.com"     → value = "new@b.com" (set overwrites)
t4: unset               → value = None
t5: set_once "z@b.com"  → value = "z@b.com" (was unset, so set_once applies)
```

### Potential inconsistency with $unset

**Problem:** If an `$unset` happened during the bug window, but a `$set` happened AFTER the bug window, this reconciliation would incorrectly delete the property.

Example:

```text
t1 (bug window):    $unset "email"     → resolved as deletion
t2 (after window):  $set "email"="x"   → not seen by reconciliation
```

The reconciliation would delete `email`, even though it was legitimately set after the bug window.

**Solution:** Compare resolved operation timestamp against `properties_last_updated_at` from Postgres before applying:

```python
def reconcile_person_properties(person, resolved_updates, resolved_deletions):
    properties = dict(person["properties"] or {})
    properties_last_updated_at = dict(person["properties_last_updated_at"] or {})

    # Apply updates (only if our timestamp is newer)
    for key, (value, event_ts) in resolved_updates.items():
        existing_ts = properties_last_updated_at.get(key)
        if existing_ts is None or event_ts > parse_datetime(existing_ts):
            properties[key] = value
            properties_last_updated_at[key] = event_ts.isoformat()

    # Apply deletions (only if our timestamp is newer)
    for key, event_ts in resolved_deletions.items():
        existing_ts = properties_last_updated_at.get(key)
        if existing_ts is None or event_ts > parse_datetime(existing_ts):
            properties.pop(key, None)
            properties_last_updated_at.pop(key, None)

    return properties, properties_last_updated_at
```

This ensures we only apply operations that are actually newer than what's currently in Postgres, preventing overwrites of legitimate post-bug-window updates.

### Critical issue: properties_last_updated_at is NOT maintained

**Discovery:** `properties_last_updated_at` is only set at person creation time (`person-create-service.ts:34-42`). It is NOT updated when properties change after creation.

This means:

- If a property is added after person creation, it has no timestamp in `properties_last_updated_at`
- The reconciliation logic checks `if existing_ts_str is None` and applies the update
- This causes post-bug-window updates to be incorrectly overwritten

**Test case:** `TestPostBugWindowUpdatePreservation::test_post_bug_window_update_should_not_be_overwritten`

Timeline:

```text
t1: Person created WITHOUT property P
t2: Bug window starts
t2.5: Event sets P=V1 (missed due to bug)
t3: Bug window ends
t3.5: Event sets P=V2 (correctly applied)
t4: Reconciliation runs
```

Current state in Postgres:

- `properties["P"] = "V2"` (from t3.5)
- `properties_last_updated_at["P"] = undefined` (not set because P was added after creation)

Reconciliation logic:

```python
existing_ts_str = properties_last_updated_at.get("P")  # None!
if existing_ts_str is None or event_ts > parse_datetime(existing_ts_str):
    properties["P"] = "V1"  # BUG: overwrites V2 with older V1
```

**This test currently FAILS** - documenting the bug that needs to be fixed.

**Integration tests confirming this behavior:**
`nodejs/src/ingestion/person-properties-metadata.e2e.test.ts`

These tests verify that:

For `properties_last_updated_at`:

1. IS set at person creation (via `$set` or `$identify`)
2. Is NOT updated when an existing property is changed
3. Does NOT get a new entry when a new property is added after creation

For `properties_last_operation`:

1. IS set at person creation with correct operation type (`set` or `set_once`)
2. Is NOT updated when properties change after creation
3. Does NOT get a new entry when a new property is added after creation
