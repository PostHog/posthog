# Precalculated Person Property System

## Overview

The precalculated person property system enables real-time cohort calculations based on person property filters by pre-evaluating person properties against cohort filter conditions and storing the results for fast lookup.

## Architecture

### Tables

#### `precalculated_person_property_sharded`

- Engine: ReplacingMergeTree with `_timestamp` as version column
- Sharding: `sipHash64(person_id)` for person-centric queries
- Partitioning: `toYYYYMM(date)` for monthly lifecycle management
- Order: `(team_id, condition, person_id)` for efficient filtering

**Schema:**

```sql
team_id         Int64
date            Date
person_id       UUID
condition       String      -- 16-char conditionHash
matches         Int8        -- 0 = no match, 1 = match
source          String      -- e.g., "cohort_filter_{conditionHash}"
_timestamp      DateTime64(6)
_partition      UInt64
_offset         UInt64
```

#### `precalculated_person_property`

- Engine: Distributed table over sharded table
- Used for queries across all shards

#### Kafka & Materialized View

- Kafka table: `kafka_precalculated_person_property`
- MV: `precalculated_person_property_mv` (writes to sharded table)
- Topic: `clickhouse_prefiltered_person_properties`

### Data Flow

```text
┌─────────────────┐
│ clickhouse_     │
│ person topic    │
└────────┬────────┘
         │
         v
┌────────────────────────────────┐
│ CdpPersonPropertyEventsConsumer│
│ - Reads person updates         │
│ - Evaluates person properties  │
│ - ALWAYS emits (0 or 1)        │
└────────┬───────────────────────┘
         │
         v
┌──────────────────────────────────┐
│ clickhouse_prefiltered_          │
│ person_properties topic          │
└────────┬─────────────────────────┘
         │
         v
┌────────────────────────────────┐
│ ClickHouse Materialized View   │
│ → precalculated_person_property│
└────────────────────────────────┘
```

## Key Design Decisions

### Always Emit (Matches AND Non-Matches)

**Critical Difference from Events:**

- Events are immutable → only emit matches
- Persons are mutable → **ALWAYS emit** (both matches=0 and matches=1)

**Rationale:**
Person properties can change over time. A person who matched yesterday might not match today, and vice versa. We need to track the current state by always emitting evaluations.

Example:

```text
Time 0: Person has email="test@company.com", matches email filter → emit matches=1
Time 1: Person email changes to "personal@gmail.com", no longer matches → emit matches=0
Time 2: Person email changes back to "work@company.com", matches again → emit matches=1
```

### Query Pattern: argMax for Latest State

**DO NOT** rely on ReplacingMergeTree compaction. Always use `argMax`:

```sql
SELECT person_id
FROM (
    SELECT
        person_id,
        argMax(matches, _timestamp) as latest_matches
    FROM precalculated_person_property
    WHERE
        team_id = {team_id}
        AND condition = {condition_hash}
    GROUP BY person_id
    HAVING latest_matches = 1
)
```

This ensures you get the most recent evaluation without depending on when ClickHouse decides to compact.

### Person Merges

When person A merges into person B:

1. Natural re-evaluation occurs (person update emitted after merge)
2. Old person_id data becomes orphaned but harmless
3. Query-time filtering via persons table removes deleted persons

## Consumer Implementation

### CdpPersonPropertyEventsConsumer

Located: `plugin-server/src/cdp/consumers/cdp-person-property-events.consumer.ts`

**Input:** `clickhouse_person` topic
**Output:** `clickhouse_prefiltered_person_properties` topic

**Batch Processing Flow:**

1. Parse Kafka messages and group by team_id
2. Fetch all realtime supported filters for those teams (filter_type='person_property')
3. For each person in each team:
   - Evaluate person against each person property filter using HogQL bytecode
   - ALWAYS emit result (matches=0 or matches=1)

**Bytecode Execution:**

```typescript
const globals = {
    person: {
        id: person.id,
        properties: personProperties,
    },
    project: {
        id: person.team_id,
    },
};

const { execResult } = await execHog(filter.bytecode, { globals });
return execResult?.result ?? false;
```

## Filter Manager Integration

### Filter Type Discrimination

`RealtimeSupportedFilterManagerCDP` extracts both behavioral and person property filters:

```typescript
// Determine filter type based on node type
let filterType: FilterType;
if (node.type === 'person') {
    filterType = 'person_property';
} else if (node.type === 'behavioral') {
    filterType = 'behavioral';
} else {
    filterType = 'behavioral'; // Default
}
```

Consumers filter for their appropriate type:

- `CdpBehaviouralEventsConsumer` → `filter_type === 'behavioral'`
- `CdpPersonPropertyEventsConsumer` → `filter_type === 'person_property'`

## HogQL Query Integration

### HogQLRealtimeCohortQuery.get_person_condition

Overrides the base cohort query method to use precalculated results:

```python
def get_person_condition(self, prop: Property) -> ast.SelectQuery:
    condition_hash = getattr(prop, "conditionHash", None)

    query_str = """
        SELECT person_id as id
        FROM (
            SELECT
                person_id,
                argMax(matches, _timestamp) as latest_matches
            FROM precalculated_person_property
            WHERE
                team_id = {team_id}
                AND condition = {condition_hash}
            GROUP BY person_id
            HAVING latest_matches = 1
        )
        WHERE person_id IN (
            SELECT id FROM persons WHERE team_id = {team_id} AND is_deleted = 0
        )
    """
```

## Cohort API

### conditionHash Generation

Located: `posthog/api/cohort.py:generate_cohort_filter_bytecode`

For person property filters:

```python
property_obj = Property(**filter_data)
expr = property_to_expr(property_obj, team)
bytecode = create_bytecode(expr, cohort_membership_supported=True).bytecode

# Generate conditionHash from bytecode
bytecode_str = json.dumps(bytecode, sort_keys=True)
condition_hash = hashlib.sha256(bytecode_str.encode()).hexdigest()[:16]
```

The `FilterBytecodeMixin` automatically adds `bytecode` and `conditionHash` to person property filters in cohort definitions.

## Monitoring

### Metrics

- **Histogram:** `cdp_person_property_batch_processing_steps_duration_ms`
  - Tracks time spent in different processing steps
  - Labels: `step`
  - Buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500]ms

### Health Checks

The consumer implements `isHealthy()` delegating to Kafka consumer health status.

## Limitations & Future Work

### Current Limitations

1. **No backfill:** Only processes person updates going forward
2. **Full evaluation:** Evaluates every person update for now (no optimization)
3. **Supported filters:** Only person property filters with inline bytecode
4. **No compound filters:** Each condition evaluated independently

### Future Optimizations

1. **Selective evaluation:** Only evaluate persons when relevant properties change
2. **Backfill mechanism:** Process existing persons for newly created cohorts
3. **Batch compaction:** Periodic cleanup of orphaned person_id records
4. **Multi-condition optimization:** Evaluate multiple conditions in single pass

## Deployment Considerations

### Prerequisites

1. ClickHouse tables created via migration `0182_precalculated_person_property.py`
2. Kafka topic `clickhouse_prefiltered_person_properties` exists
3. Consumer enabled via `cdpBehaviouralEvents` capability flag

### Rollout Strategy

The implementation follows a gradual rollout approach:

**Phase 1: Infrastructure** ✅

- Create ClickHouse tables
- Create Kafka topics
- No production data flow

**Phase 2: Shadow Mode** (Next)

- Enable consumer
- Process data but don't use in queries
- Monitor performance and data quality

**Phase 3: Limited Production**

- Enable for small subset of teams
- Monitor impact on query performance
- Verify data accuracy

**Phase 4: Full Rollout**

- Enable for all realtime cohorts
- Monitor at scale

### Monitoring During Rollout

Key metrics to watch:

- Consumer lag on `clickhouse_person` topic
- Processing time per batch
- Error rates in bytecode execution
- ClickHouse disk usage for precalculated_person_property
- Query performance improvements

## Troubleshooting

### Common Issues

**Issue: Consumer not processing messages**

- Check capability flag `cdpBehaviouralEvents` is enabled
- Verify filter_type='person_property' filters exist in database
- Check Kafka consumer group lag

**Issue: Incorrect cohort membership**

- Verify conditionHash matches between cohort definition and consumer
- Check `argMax(matches, _timestamp)` returns expected value
- Verify person is not deleted (`is_deleted=0` in persons table)

**Issue: High memory usage**

- Check number of teams processed per batch
- Monitor filter count per team
- Consider batching optimizations

## Related Documentation

- Precalculated Events: `posthog/models/precalculated_events/`
- Realtime Cohorts: `posthog/models/cohort/`
- HogQL Bytecode: `posthog/hogql/compiler/bytecode.py`
- CDP Consumers: `plugin-server/src/cdp/consumers/`
