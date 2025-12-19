# Event Properties EAV Table Implementation

This document tracks the implementation of the EAV (Entity-Attribute-Value) table for event properties optimization.

## Overview

The EAV table provides faster property access for high-volume customers by storing selected properties in a separate table with typed columns, avoiding the need to read large JSON blobs from the `properties` column.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                        Query Flow                                │
├─────────────────────────────────────────────────────────────────┤
│  HogQL Query: SELECT properties.plan FROM events                │
│                           │                                      │
│                           ▼                                      │
│  PropertySwapper detects EAV slot for "plan"                    │
│                           │                                      │
│                           ▼                                      │
│  EAVJoinRewriter marks PropertyType with eav_alias/eav_column   │
│                           │                                      │
│                           ▼                                      │
│  Printer generates:                                              │
│    SELECT eav_plan.value_string                                  │
│    FROM events                                                   │
│    ANY LEFT JOIN event_properties AS eav_plan                   │
│      ON events.team_id = eav_plan.team_id                       │
│      AND toDate(events.timestamp) = toDate(eav_plan.timestamp)  │
│      AND events.event = eav_plan.event                          │
│      AND cityHash64(events.distinct_id) = ...                   │
│      AND cityHash64(events.uuid) = ...                          │
│      AND eav_plan.key = 'plan'                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Status

### Phase 1: Base Schema ✅ COMPLETE

**Branch:** `eav_event_properties`

| File | Description |
|------|-------------|
| `posthog/models/event_properties/__init__.py` | Package init |
| `posthog/models/event_properties/sql.py` | ClickHouse table definitions |
| `posthog/clickhouse/migrations/0193_event_properties_eav_table.py` | ClickHouse migration |
| `posthog/models/materialized_column_slots.py` | Added `MaterializationType` enum and field |
| `posthog/migrations/0951_add_materialization_type_to_materialized_column_slot.py` | Django migration |

**Table Schema:**

```sql
CREATE TABLE sharded_event_properties (
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    event String,
    distinct_id String,
    uuid UUID,
    key String,
    value_string Nullable(String),
    value_numeric Nullable(Float64),
    value_bool Nullable(UInt8),
    value_datetime Nullable(DateTime64(6, 'UTC')),
    _timestamp DateTime,
    _partition UInt64,
    _offset UInt64
)
ENGINE = ReplacingMergeTree(_timestamp)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid), key)
```

### Phase 2: HogQL Support ✅ COMPLETE

**Branch:** `eav_event_properties_hogql`

| File | Description |
|------|-------------|
| `posthog/hogql/transforms/property_types.py` | EAV slot detection in PropertySwapper |
| `posthog/hogql/transforms/eav_joins.py` | EAVPropertyFinder and EAVJoinRewriter |
| `posthog/hogql/printer.py` | JOIN generation for EAV properties |
| `posthog/hogql/transforms/test/test_eav_joins.py` | Tests (5 passing) |

### Phase 3: Frontend UI ❌ NOT STARTED

Needed:

- UI in Data Management for selecting materialization type
- Dropdown: "Dynamic Materialized Column (DMAT)" vs "EAV Table"
- Trigger appropriate backfill workflow based on selection

### Phase 4: Ingestion ❌ NOT STARTED

Needed:

- Plugin-server changes to check for EAV-enabled properties
- Write to `clickhouse_event_properties` Kafka topic
- Cache `MaterializedColumnSlot` data in TeamManager

### Phase 5: Backfill Workflow ✅ COMPLETE

**Branch:** `eav_backfill`

| File | Description |
|------|-------------|
| `posthog/temporal/eav_backfill/__init__.py` | Module exports |
| `posthog/temporal/eav_backfill/activities.py` | `backfill_eav_property`, `update_eav_slot_state` |
| `posthog/temporal/eav_backfill/workflows.py` | `BackfillEAVPropertyWorkflow` |
| `posthog/temporal/product_analytics/__init__.py` | Workflow registration |
| `posthog/temporal/tests/eav_backfill/` | Tests (3 passing) |

## Testing Locally

### 1. Run Migrations

```bash
git checkout eav_backfill
python manage.py migrate
DEBUG=1 python manage.py migrate_clickhouse
```

### 2. Create Test EAV Slot

```python
from posthog.models import Team, PropertyDefinition, MaterializedColumnSlot
from posthog.models.materialized_column_slots import MaterializationType, MaterializedColumnSlotState

team = Team.objects.get(id=YOUR_TEAM_ID)

prop_def, _ = PropertyDefinition.objects.get_or_create(
    team=team,
    name="plan",
    defaults={"property_type": "String", "type": PropertyDefinition.Type.EVENT}
)

slot = MaterializedColumnSlot.objects.create(
    team=team,
    property_definition=prop_def,
    property_type="String",
    slot_index=0,
    state=MaterializedColumnSlotState.READY,
    materialization_type=MaterializationType.EAV,
)
```

### 3. Test HogQL Query

```python
from posthog.hogql.query import execute_hogql_query

result = execute_hogql_query(
    "SELECT properties.plan FROM events WHERE event = '$pageview' LIMIT 10",
    team=team,
)
print(result.clickhouse)  # Should show ANY LEFT JOIN event_properties
```

### 4. Test Backfill Workflow

Requires Temporal to be running:

```bash
python manage.py run_temporal_workflow backfill-eav-property \
    '{"team_id": 1, "slot_id": "UUID", "property_name": "plan", "property_type": "String"}'
```

## Deployment Checklist

- [ ] Merge `eav_backfill` branch (contains all implemented changes)
- [ ] Create `clickhouse_event_properties` Kafka topic
- [ ] Verify ClickHouse migration runs successfully
- [ ] Implement frontend UI (Phase 3)
- [ ] Implement plugin-server ingestion (Phase 4)
- [ ] End-to-end testing with real data

## Related Links

- Original spec: (internal document)
- Branches:
  - `eav_event_properties` - Base schema
  - `eav_event_properties_hogql` - HogQL support
  - `eav_backfill` - Backfill workflow (contains all changes)

## Property Type Mapping

| PropertyDefinition.property_type | EAV Column | DMAT Column |
|----------------------------------|------------|-------------|
| String | `value_string` | `dmat_string_N` |
| Numeric | `value_numeric` | `dmat_numeric_N` |
| Boolean | `value_bool` | `dmat_bool_N` |
| DateTime | `value_datetime` | `dmat_datetime_N` |
