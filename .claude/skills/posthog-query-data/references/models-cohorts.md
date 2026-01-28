# Cohorts & Persons

## Cohort (`posthog_cohort`)

Cohorts are groups of persons used for segmentation and targeting.

### Columns

Column | Type | Nullable | Description
`id` | integer | NOT NULL | Primary key (auto-generated)
`name` | varchar(400) | NULL | Cohort display name
`description` | varchar(1000) | NOT NULL | Cohort description
`deleted` | boolean | NOT NULL | Soft delete flag
`filters` | jsonb | NULL | Modern filter structure for cohort criteria
`query` | jsonb | NULL | HogQL query for analytical cohorts
`version` | integer | NULL | Current calculation version
`pending_version` | integer | NULL | Version being calculated
`count` | integer | NULL | Cached person count
`created_at` | timestamp with tz | NULL | Creation timestamp
`is_calculating` | boolean | NOT NULL | Whether calculation is in progress
`last_calculation` | timestamp with tz | NULL | Timestamp of last successful calculation
`errors_calculating` | integer | NOT NULL | Consecutive error count
`last_error_at` | timestamp with tz | NULL | Timestamp of last calculation error
`is_static` | boolean | NOT NULL | Static (manually uploaded) vs dynamic cohort
`cohort_type` | varchar(50) | NULL | One of: `static`, `person_property`, `behavioral`, `realtime`, `analytical`
`created_by_id` | integer | NULL | FK to `posthog_user.id`

### HogQL Queryable Fields

Available via `system.cohorts`:

- `id`, `name`, `description`, `deleted`, `filters`, `groups`, `query`, `created_at`, `last_calculation`, `version`, `count`, `is_static`

### Cohort Types

Type | Description
`static` | Manually uploaded/managed list of persons
`person_property` | Based on person properties (e.g., email contains "example.com")
`behavioral` | Based on events performed (e.g., "viewed pricing page in last 30 days")
`realtime` | Can be evaluated in real-time (< 20M persons)
`analytical` | Complex queries with temporal/sequential logic via HogQL

### Filters Structure Examples

**Behavioral filter (performed event):**

```json
{
  "properties": {
    "type": "OR",
    "values": [
      {
        "key": "address page viewed",
        "type": "behavioral",
        "value": "performed_event",
        "negation": false,
        "event_type": "events",
        "time_value": "30",
        "time_interval": "day"
      }
    ]
  }
}
```

**Person property filter:**

```json
{
  "properties": {
    "type": "OR",
    "values": [
      {
        "key": "email",
        "type": "person",
        "value": ["@example.com"],
        "negation": false,
        "operator": "icontains"
      }
    ]
  }
}
```

**Cohort reference filter (nested cohorts):**

```json
{
  "properties": {
    "type": "OR",
    "values": [
      {
        "key": "id",
        "type": "cohort",
        "value": 8814,
        "negation": false
      }
    ]
  }
}
```

### Key Relationships

- **Created By**: `created_by_id` -> `posthog_user.id`
- **Persons**: Many-to-many via `posthog_cohortpeople`
- **Calculation History**: One-to-many via `posthog_cohortcalculationhistory`
- **Experiments**: Referenced by `posthog_experiment.exposure_cohort_id`

### Important Notes

- Cohorts can reference other cohorts creating nested dependencies
- `realtime` cohorts are cleared to `NULL` type if they exceed 20M persons
- Static cohorts are populated via CSV upload or API
- Dynamic cohorts are recalculated periodically

---

## Cohort People (`posthog_cohortpeople`)

Junction table connecting cohorts to persons.

### Columns

Column | Type | Nullable | Description
`id` | bigint | NOT NULL | Primary key (auto-generated)
`cohort_id` | integer | NOT NULL | FK to `posthog_cohort.id`
`person_id` | bigint | NOT NULL | FK to `posthog_person.id`
`version` | integer | NULL | Cohort calculation version that included this person

### Indexes

- Primary key on `id`
- Composite index on `(cohort_id, person_id)`
- Index on `cohort_id`
- Index on `person_id`

### Important Notes

- `version` tracks which cohort calculation added this membership
- During recalculation, old versions are cleaned up
- Table migrations managed via Rust (persons_migrations)

---

## Cohort Calculation History (`posthog_cohortcalculationhistory`)

Audit trail for cohort calculation jobs.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`filters` | jsonb | NOT NULL | Cohort filters at calculation time
`count` | integer | NULL | Number of persons in cohort (>= 0)
`started_at` | timestamp with tz | NOT NULL | Calculation start time
`finished_at` | timestamp with tz | NULL | Calculation end time (NULL = in progress)
`queries` | jsonb | NULL | Array of query statistics
`error` | text | NULL | Full error message if failed
`error_code` | varchar(64) | NULL | Categorized error code
`cohort_id` | integer | NOT NULL | FK to `posthog_cohort.id`

### Error Codes

Code | Description
`capacity` | System busy
`interrupted` | Socket timeout
`timeout` | Query timeout (> 1200s)
`memory_limit` | Memory exceeded
`query_size` | Query too large
`invalid_regex` | Regex compilation error
`incompatible_types` | Type mismatch
`no_properties` | No filters defined
`validation_error` | Generic validation error

### Queries Structure

```json
[
  {
    "query": "SELECT ...",
    "query_id": "abc123",
    "query_ms": 1234,
    "memory_mb": 256,
    "read_rows": 1000000,
    "written_rows": 5000
  }
]
```

---

## Person (`posthog_person`)

Represents an individual user tracked by PostHog.

### Columns

Column | Type | Nullable | Description
`id` | bigint | NOT NULL | Primary key (auto-generated)
`uuid` | uuid | NOT NULL | Unique identifier used in ClickHouse
`created_at` | timestamp with tz | NOT NULL | Person creation timestamp
`properties` | jsonb | NOT NULL | Person properties (max 640KB)
`properties_last_updated_at` | jsonb | NULL | Per-property update timestamps
`properties_last_operation` | jsonb | NULL | Per-property operation type
`is_identified` | boolean | NOT NULL | Whether person has been identified
`version` | bigint | NULL | Version for ClickHouse sync
`is_user_id` | integer | NULL | Legacy user ID

### Key Relationships

- **Distinct IDs**: One-to-many via `posthog_persondistinctid`
- **Cohorts**: Many-to-many via `posthog_cohortpeople`

### Important Notes

- `uuid` is the stable identifier used across ClickHouse and PostgreSQL
- `properties` has a size constraint of 640KB
- Multiple distinct IDs can map to a single person (identity merging)

---

## Person Distinct ID (`posthog_persondistinctid`)

Maps distinct IDs (anonymous or identified) to person records.

### Columns

Column | Type | Nullable | Description
`id` | bigint | NOT NULL | Primary key (auto-generated)
`distinct_id` | varchar(400) | NOT NULL | The distinct ID string
`version` | bigint | NULL | Version for sync
`person_id` | bigint | NOT NULL | FK to `posthog_person.id`

### Important Notes

- Distinct IDs can be anonymous UUIDs or identified user IDs
- When persons merge, their distinct IDs are combined
- The `$identify` call links anonymous to identified distinct IDs

---

## Entity Relationships Diagram

```text
posthog_cohort (main cohort definition)
├── created_by_id -> posthog_user.id
├── <-M:N-> posthog_person via posthog_cohortpeople
└── <- posthog_cohortcalculationhistory.cohort_id

posthog_cohortpeople (junction table)
├── cohort_id -> posthog_cohort.id
└── person_id -> posthog_person.id

posthog_person
├── <- posthog_persondistinctid.person_id
└── <-M:N-> posthog_cohort via posthog_cohortpeople

posthog_persondistinctid
├── person_id -> posthog_person.id

posthog_experiment
└── exposure_cohort_id -> posthog_cohort.id
```

---

## Common Query Patterns

**Find cohorts by name:**

```sql
SELECT id, name, count, cohort_type, is_static
FROM system.cohorts
WHERE name ILIKE '%paying%' AND NOT deleted
```

**Get cohort with member count:**

```sql
SELECT c.id, c.name, c.count, c.last_calculation
FROM system.cohorts c
WHERE c.id = 123
```

**List persons in a cohort (via events):**

```sql
SELECT DISTINCT person_id, person.properties.email
FROM events
WHERE person_id IN COHORT 123
LIMIT 100
```

**Check cohort calculation history:**

```sql
SELECT id, started_at, finished_at, count, error_code
FROM system.cohort_calculation_history
WHERE cohort_id = 123
ORDER BY started_at DESC
LIMIT 10
```
