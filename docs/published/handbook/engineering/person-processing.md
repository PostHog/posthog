---
title: Person processing in PostHog
sidebar: Handbook
showTitle: true
---

> **Note**: This document describes the person processing system at a point in time. The source of truth is, as always, the source code. If you find a mistake or something out of date, please open a PR!

> It's not intended to provide a perfectly detailed view of any one system, rather it should explain how they fit together at a high level, going into detail when relevant.

## Introduction

PostHog's person processing system provides **stable identity** for users across multiple sessions, devices, and platforms. A single real-world user (a "Person") may interact with your product from their phone, laptop, and through server-side API calls - person processing ensures all of these interactions are attributed to the same identity.

### What person processing enables

- **Uniqueness counts**: Accurate counts of unique users (not just unique sessions or device IDs)
- **Cross-session analysis**: Funnels, retention, and journeys that span multiple sessions
- **Cross-device attribution**: A user who browses on mobile and converts on desktop is tracked as one person
- **Person profiles**: Storing properties like email, name, initial referrer, subscription tier, or any custom property
- **Targeting and personalization**: Feature flags, experiments, and cohorts can target users based on person properties

Person profiles power many PostHog products:

- **Analytics**: Filter and breakdown by person properties, measure funnel conversion or retention
- **Feature flags**: Target users by properties, ensure consistent flag values across sessions
- **Experiments**: Assign users to variants consistently, analyze results by person properties
- **Cohorts**: Define groups of users based on behavior and properties

---

## System overview

Events flow through several systems before they're queryable:

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Client SDK                                                                    │
│   (posthog-js, posthog-node, etc.)                                             │
│                                                                                 │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Capture (Rust service)                                                        │
│   - Validates events                                                            │
│   - Rate limiting / overflow                                                    │
│   - Produces to Kafka                                                           │
│   - Partition key: <token>:<distinct_id>                                        │
│                                                                                 │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Kafka (events_plugin_ingestion topic)                                         │
│   - Partitioned by token:distinct_id                                            │
│   - Events for same distinct_id go to same partition (ordering guarantee)       │
│   - Different distinct_ids may go to different partitions (no ordering)         │
│                                                                                 │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Ingestion Pipeline (Node.js) - formerly called Plugin Server                                  │
│   - Person processing (creates/updates/merges persons in PostgreSQL)            │
│   - Property updates ($set, $set_once, $unset)                                  │
│   - Produces person updates to Kafka                                            │
│   - Produces processed events to Kafka                                          │
│                                                                                 │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Kafka (clickhouse_events_json, person topics)                                 │
│                                                                                 │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ClickHouse                                                                    │
│   - events table (with person_id column)                                        │
│   - person table                                                                │
│   - person_distinct_id2 table (distinct_id → person mapping)                    │
│   - person_distinct_id_overrides table (for squashing)                          │
│                                                                                 │
└─────────────────────────────────┬───────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   HogQL / Query Engine                                                          │
│   - Translates queries to ClickHouse SQL                                        │
│   - Handles person joins based on PoE (Persons on Events) mode                  │
│   - Applies person_distinct_id_overrides when needed                            │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Key concepts

### Distinct ID

A `distinct_id` is an identifier attached to every event. It's how we know which person an event belongs to. A person can have multiple distinct IDs (e.g., an anonymous session ID and a logged-in user ID).

A user's distinct ID is provided by the client as part of the `identify` call. Before identify is called, the distinct ID is a randomly generated UUID.

Some commonly used Distinct ID formats are: the user's email address, a UUID randomly generated by a client SDK, the primary key id in the customer's `User` table in their database, a Stripe `cus_xxx` ID.

A distinct ID must be associated with exactly one user, so it'd be invalid to use e.g. "backend", "python", or anything that relates to a class of users rather than individual.

### Person UUID

Every person has a single UUID, generated deterministically from `(team_id, distinct_id)` at creation time using UUIDv5.

```typescript
// nodejs/src/worker/ingestion/person-uuid.ts
function uuidFromDistinctId(teamId: number, distinctId: string): string {
  return uuidv5(`${teamId}:${distinctId}`, PERSON_UUIDV5_NAMESPACE)
}
```

### Person profile

A person profile contains:

- **Properties**: Key-value pairs (email, name, plan, custom properties)
- **is_identified**: Whether this person has been explicitly identified (via `$identify`)
- **created_at**: When the person was first seen

### The identify flow

When a user identifies themselves (typically on login), the SDK calls `$identify` with:

- `distinct_id`: The identified user ID (e.g., email, user ID from your database)
- `$anon_distinct_id`: The anonymous ID that was being used before login

This triggers a **merge**: all events from both the anonymous distinct ID and the identified ID should be attributed to the same person. We do this through a level of indirection (a join between persons_ids and distinct_ids) which we explain in more depth later on.

---

## Edge cases and optimizations

### Person ID squashing

#### Why do we need this?

When a user identifies themselves, there's a problem: historical events in ClickHouse still have the old `person_id`. If we do nothing, queries for that user would miss all their anonymous events.

The naive solution is to JOIN the events table with a mapping table (`person_distinct_id2`) that knows which distinct_ids belong to which person. But `person_distinct_id2` contains **every** distinct_id mapping for **every** user - this table can have hundreds of millions of rows. Joining the events table (which can have billions of rows) with this massive mapping table on every query is prohibitively slow.

#### The overrides approach

Instead, we use a two-part strategy, which involves

1. **Periodically rewriting the `person_id` on events to respect these merges**: We call this process squashing. Once events are rewritten, we delete those rows from `person_distinct_id_overrides`. This keeps the overrides table small.

2. **Small overrides table for queries**: We maintain `person_distinct_id_overrides` which only contains distinct_ids whose person mapping has **changed** (i.e., been merged) since the last squash. This table is tiny compared to `person_distinct_id2` - typically just thousands of rows instead of millions. Queries can quickly LEFT JOIN to this small table instead of the massive overrides table.

#### How squashing works

1. When a distinct_id's person mapping changes (during merge) with `version > 0`, a row is inserted into `person_distinct_id_overrides`
2. A scheduled job (`posthog/dags/person_overrides.py`) periodically:
   - Creates a snapshot of pending overrides
   - Uses a ClickHouse dictionary to efficiently look up the new person_id
   - Runs an `ALTER TABLE ... UPDATE` mutation to rewrite person_ids in the events table
   - Deletes the processed overrides
3. Until squashing completes, queries LEFT JOIN to `person_distinct_id_overrides` to get the correct person_id

The result: queries stay fast because they only join with a small table, and that table stays small because we continuously squash and clean up.

### Personless mode (anonymous events)

> **Terminology**: In user-facing documentation, these are called "anonymous events". Internally, we call them "personless events". They're the same thing.

#### Why do personless events exist?

Much of the per-event cost of ingestion comes from person processing - looking up persons in PostgreSQL, creating/updating records, handling merges, and producing to multiple Kafka topics. By skipping person processing for some events, we can offer significantly lower pricing.

The typical use case: most of your traffic is logged-out users browsing your site. You don't need person profiles for these users - you just want to count pageviews and track basic analytics. But when a user logs in, makes a purchase, or does something valuable, you want full person tracking so you can analyze their journey, target them with feature flags, etc.

We put significant engineering effort into making the transition from personless to identified work seamlessly - when a user identifies, their previous anonymous events are linked to their new person profile automatically.

#### How it works

By default, every event creates or updates a person profile. Personless mode (`$process_person_profile: false`) skips this:

- Events are ingested with a deterministic "fake" person UUID (computed from the distinct_id)
- No person record is created in PostgreSQL
- No person properties are stored or available
- Ingestion is faster and uses fewer resources

If a personless user later identifies themselves via `$identify`, an override is created to link their anonymous events to their real person. This gives you the best of both worlds: cheap ingestion for anonymous users, full person support once they identify.

---

## Detailed component walkthrough

### 1. Capture (Rust / Kafka)

**Location**: `rust/capture/`

**Responsibilities**:

- Receive events via HTTP
- Validate and normalize event data
- Apply rate limiting and overflow handling
- Produce events to Kafka

**Key behavior for person processing**:

**Kafka Topic**: `events_plugin_ingestion`

The Kafka partition key for most events is `<token>:<distinct_id>`:

```rust
// rust/common/types/src/event.rs
  pub fn key(&self) -> String {
      if self.is_cookieless_mode {
          format!("{}:{}", self.token, self.ip)
      } else {
          format!("{}:{}", self.token, self.distinct_id)
      }
  }
```

(Cookieless events use a placeholder distinct ID, which is replaced later with a privacy-preserving hash. The placeholder is not suitable as a partioning key, as it is always the same value for every cookieless event, so IP address is used)

**Implications**:

- Events with the **same** distinct_id go to the **same** Kafka partition → ordering preserved
- Events with **different** distinct_ids may go to **different** partitions → no ordering guarantee
- Note: Unfortunately this means an anonymous event and its corresponding `$identify` event (which has a different distinct_id) can be processed in parallel by different workers, the ingestion pipeline code is careful to avoid race conditions here.

### 2. Ingestion pipeline (Node.js)

**Location**: `nodejs/src/worker/ingestion/`

The ingestion pipeline processes events in batches. For person processing:

#### 2.1 Prefetch step

**Location**: `nodejs/src/worker/ingestion/event-pipeline/prefetchPersonsStep.ts`

- Batch-fetches persons for all distinct_ids in the batch
- Populates a cache to avoid repeated database lookups

#### 2.2 Personless batch step

**Location**: `nodejs/src/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep.ts`

For events with `$process_person_profile: false`:

- Batch-inserts into `posthog_personlessdistinctid` table
- Checks and caches whether the distinct_id was already merged (`is_merged` flag)

```sql
-- nodejs/src/worker/ingestion/persons/repositories/postgres-person-repository.ts
INSERT INTO posthog_personlessdistinctid (team_id, distinct_id, is_merged, created_at)
VALUES ($1, $2, false, now())
ON CONFLICT (team_id, distinct_id) DO UPDATE
SET is_merged = posthog_personlessdistinctid.is_merged
RETURNING is_merged
```

#### 2.3 Person processing step

**Location**: `nodejs/src/worker/ingestion/event-pipeline/processPersonsStep.ts`

Two branches based on `$process_person_profile`:

**If `$process_person_profile: false` (personless mode)**:

1. Check if a real person exists for this distinct_id
2. If yes, use that person, and treat this like an identified event as long as the person was created more than one minute earlier (to avoid race conditions with identify).
3. If no, create a "fake" person with deterministic UUID
4. Event gets the fake person's UUID

**If `$process_person_profile: true` (or not set)**:

1. Check if person exists for this distinct_id
2. If not, create a new person
3. Apply property updates ($set, $set_once, $unset)
4. If this is an `$identify` event, handle the merge

#### 2.4 Merge handling

**Location**: `nodejs/src/worker/ingestion/persons/person-merge-service.ts`

When `$identify` is called with `$anon_distinct_id`:

```typescript
// nodejs/src/worker/ingestion/persons/person-merge-service.ts
async mergeDistinctIds(
    otherPersonDistinctId: string,    // e.g., "anon-123"
    mergeIntoDistinctId: string,      // e.g., "user@example.com"
    teamId: number,
    timestamp: DateTime
)
```

**Three cases**:

1. **Only one person exists**: Add the missing distinct_id to that person
2. **Both persons exist**: Merge them (move all distinct_ids, merge properties, delete source person)
3. **Neither exists**: Create a new person with both distinct_ids

**When are overrides created?**

An override is needed when events exist in ClickHouse with a person_id that's now incorrect (because of a merge). The `version` field in `posthog_persondistinctid` controls this:

- `version = 0`: No override - this distinct_id's events already have the correct person_id (e.g. the first `$identify` for a user, due to the deterministic UUID v5)
- `version >= 1`: Override created - events exist with an old person_id that needs rewriting

### 4. PostgreSQL tables

**`posthog_person`**: The source of truth for person data

- `id`: Internal integer ID
- `uuid`: The person's UUID (deterministic from primary distinct_id)
- `team_id`: Which team this person belongs to
- `properties`: JSONB of person properties
- `is_identified`: Whether `$identify` was called
- `version`: Incremented on updates (for ClickHouse consistency)

**`posthog_persondistinctid`**: Maps distinct_ids to persons

- `distinct_id`: The distinct ID string
- `person_id`: FK to posthog_person
- `team_id`: Which team
- `version`: 0 for primary, >=1 for merged (triggers override)

**`posthog_personlessdistinctid`**: Tracks distinct_ids used in personless mode

- `distinct_id`: The distinct ID
- `team_id`: Which team
- `is_merged`: Whether this has been merged into a real person
- Used to determine if an override is needed when merging

### 5. Kafka (person updates)

After person processing, updates are produced to Kafka:

- `KAFKA_PERSON`: Person creates/updates/deletes
- `KAFKA_PERSON_DISTINCT_ID`: Distinct ID mapping changes

### 6. ClickHouse tables

**`events`**: The main events table

- `person_id`: UUID of the person (may be outdated if merge hasn't been squashed)
- `distinct_id`: The distinct_id that was sent with the event (not changed by squashing)
- Other event data

**`person`**: [ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree) of person data

- Keeps latest version per person UUID

**`person_distinct_id2`**: All distinct_id → person mappings

- Full table, can be very large

**`person_distinct_id_overrides`**: Only pending overrides

- Populated via materialized view that filters for `version > 0`
- Small table, used for query-time corrections until squashing completes

### 7. HogQL / Query engine

HogQL is PostHog's query language - a dialect of SQL that provides useful abstractions over raw ClickHouse queries. It serves two main purposes (and many others):

1. **Abstractions**: HogQL handles complexity like person overrides, property access, and table relationships so you don't have to write complex JOINs manually
2. **Multi-tenancy**: HogQL automatically adds `team_id` filters to all queries, ensuring customers can only access their own data - this lets us safely expose SQL access to users

HogQL is smart about when to add JOINs - it only adds them when you actually need them.

#### Automatic override JOIN

If your query doesn't reference `person_id`, HogQL won't add the overrides JOIN:

```sql
-- This query doesn't need the overrides JOIN
SELECT count() FROM events WHERE event = '$pageview'
```

But if you reference `events.person_id` or `events.person.id`, HogQL automatically adds the LEFT JOIN to `person_distinct_id_overrides`:

```sql
-- HogQL adds: LEFT JOIN person_distinct_id_overrides ON ...
SELECT count() FROM events WHERE events.person.id = 'some-uuid'
```

This means queries that don't need person data stay fast, while queries that do need it get correct results (even for recently-merged persons that haven't been squashed yet).

#### Person properties: two ways to access them

**Option 1: `person.properties` (PoE)**

Person properties are stored directly on the events table at ingestion time. No JOIN needed:

```sql
-- Fast: reads directly from events table
SELECT person.properties.email FROM events
```

These properties reflect **the state at the time the event was ingested**. If a person's email changes later, historical events still show the old email.

**Option 2: `pdi.person.properties` (JOIN to person table)**

This JOINs through `person_distinct_id` to the `person` table:

```sql
-- Slower: requires JOIN to person table
SELECT pdi.person.properties.email FROM events
```

These properties reflect **the current state** of the person. All events show the person's current email, even if it was different when the event occurred.

PDI = Person Distinct ID

#### Which to use?

| Access pattern            | JOIN required? | Property state    |
| ------------------------- | -------------- | ----------------- |
| `person.properties.X`     | No             | At ingestion time |
| `pdi.person.properties.X` | Yes            | Current           |

Most queries should use `person.properties` for performance. Use `pdi.person.properties` only when you specifically need the current property values.

#### PoE mode settings

It is possible to change `person.properties` to use the PDI properties instead, using the PoE mode setting. This can be set at both the query level and the team level, though we would like to remove the team-level setting soon.
This is set through the `HogQLQueryModifiers` class.

If this setting is overridden, you can access PoE properties regardless of the PoE mode by using `poe.properties.X`

---

## Debugging tips

### Check if override exists

```sql
-- Run against ClickHouse
SELECT * FROM person_distinct_id_overrides
WHERE team_id = X AND distinct_id = 'anon-123'
```

### Check person mappings

```sql
-- Run against ClickHouse
SELECT * FROM person_distinct_id2
WHERE team_id = X AND distinct_id IN ('anon-123', 'user@example.com')
```

### Check if distinct_id was used in personless mode

```sql
-- Run against PostgreSQL
SELECT * FROM posthog_personlessdistinctid
WHERE team_id = X AND distinct_id = 'anon-123'
```

### Check person version

```sql
-- Run against PostgreSQL
SELECT * FROM posthog_persondistinctid
WHERE team_id = X AND distinct_id = 'anon-123'
-- version = 0 means primary, no override
-- version >= 1 means override should exist
```

---

## Key files

### Capture (Rust)

| File                              | Purpose                                               |
| --------------------------------- | ----------------------------------------------------- |
| `rust/capture/src/sinks/kafka.rs` | Produces events to Kafka, sets partition key          |
| `rust/common/types/src/event.rs`  | Event type, includes `key()` method for partition key |

### Ingestion pipeline (Node.js)

| File                                                                                  | Purpose                                         |
| ------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `nodejs/src/worker/ingestion/person-uuid.ts`                                          | Deterministic UUID generation                   |
| `nodejs/src/worker/ingestion/event-pipeline/processPersonsStep.ts`                    | Entry point for person processing               |
| `nodejs/src/worker/ingestion/event-pipeline/processPersonlessStep.ts`                 | Personless event handling                       |
| `nodejs/src/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep.ts` | Batch personless tracking                       |
| `nodejs/src/worker/ingestion/persons/person-merge-service.ts`                         | Merge/identify handling, override version logic |
| `nodejs/src/worker/ingestion/persons/person-create-service.ts`                        | Person creation                                 |
| `nodejs/src/worker/ingestion/persons/repositories/postgres-person-repository.ts`      | PostgreSQL queries for person operations        |

### PostgreSQL schema (Python/Django)

| File                              | Purpose                                                       |
| --------------------------------- | ------------------------------------------------------------- |
| `posthog/models/person/person.py` | Django models: Person, PersonDistinctId, PersonlessDistinctId |

### ClickHouse schema (Python)

| File                           | Purpose                                                                    |
| ------------------------------ | -------------------------------------------------------------------------- |
| `posthog/models/person/sql.py` | Person, person_distinct_id, person_distinct_id_overrides table definitions |

### Squashing job (Python)

| File                               | Purpose                                       |
| ---------------------------------- | --------------------------------------------- |
| `posthog/dags/person_overrides.py` | Dagster job that squashes person_id overrides |

### HogQL (Python)

| File                                                            | Purpose                                    |
| --------------------------------------------------------------- | ------------------------------------------ |
| `posthog/hogql/database/schema/persons.py`                      | HogQL schema for persons table             |
| `posthog/hogql/database/schema/person_distinct_ids.py`          | HogQL schema for person_distinct_id tables |
| `posthog/hogql/database/schema/person_distinct_id_overrides.py` | HogQL schema for overrides table           |
