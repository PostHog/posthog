---
name: setting-up-warehouse-properties
description: >
  Populate person or group properties from a data warehouse table or materialized view, so warehouse columns
  become properties usable in feature flags, cohorts, and insights. Use when the user wants to "sync my Postgres
  columns to person properties", "map a warehouse table to people", "replace our daily identify cron", "update
  person properties from the warehouse", or asks for reverse ETL into PostHog. Covers picking the table and the
  identifier column, proposing a whole-table column mapping in one call, excluding identity and reserved
  properties, checking collisions with properties that already exist, and running the first backfill.
---

# Setting up warehouse properties

Warehouse properties write columns from a warehouse table or materialized view onto matching people or groups,
on the schedule that table already syncs on. They replace a cron that sends `$set` identify events.

The mapping is the whole job. Most tables worth mapping are wide, so the work is deciding which columns become
properties and what they are called — not making many API calls. **One source carries the entire mapping**:
`custom-property-sources-create` takes the complete `column_property_map` in a single request, so never loop
per column.

## When to use this skill

- "Sync my `postgres.customer_attributes` columns to person properties"
- "We send a daily identify job from our warehouse, can PostHog pull it instead?"
- "Map this table to people" / "reverse ETL into PostHog"
- The user is looking at Data → Warehouse properties and wants a whole table mapped

Use `setting-up-a-data-warehouse-source` instead when the table is not in the warehouse yet. This skill starts
once the data is syncing.

## Tools

| Tool                                 | Purpose                                                                                              |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `external-data-schemas-list`         | Find a synced table and its schema id (the `external_data_schema` binding); columns are omitted here |
| `external-data-schemas-retrieve`     | Read one synced table's columns and types by schema id                                               |
| `view-list`                          | Find a materialized view and its column schema (the `saved_query` binding)                           |
| `view-get`                           | Read one materialized view's columns and types by id                                                 |
| `custom-property-definitions-list`   | See what warehouse properties already exist for the team                                             |
| `custom-property-definitions-create` | Create the definition the source attaches to (`target_type: person` or `group`)                      |
| `custom-property-sources-create`     | Bind the definition to the table, carrying the whole `column_property_map`                           |
| `custom-property-sources-backfill`   | Populate historical rows after creating the mapping                                                  |
| `custom-property-sources-runs-list`  | Check the run funnel after a sync or backfill                                                        |
| `custom-property-sources-sync`       | Run the underlying table now                                                                         |

Person and group targets need the `warehouse-person-properties` feature. A group target additionally needs the
`group:write` scope; without it, `custom-property-sources-create` refuses the group definition.

## The flow

### 1. Find the table and its columns

For a synced table, `external-data-schemas-list` gives you the schema id (the `external_data_schema` binding), and
`external-data-schemas-retrieve` returns that schema's columns and types.

For a materialized view, `view-list` finds the view and its column schema, and `view-get` returns one view's columns
by id; a view binds by `saved_query` instead, and must already be materialized, since an unmaterialized view has no
data to read and the create call rejects it.

### 2. Pick the identifier column, and say why it matters

Ask which column holds the PostHog **distinct ID** (person targets) or the **group key** (group targets). This is
the single most common reason a mapping silently does nothing, so do not guess it from a name like `id` or
`user_id` without confirming.

Two properties of the sync are worth stating plainly before the user commits:

- It **only updates people or groups that already exist** in PostHog. Rows that match nobody are skipped, and
  the run reports them as `skipped_missing_person`. It does not create people.
- **Null values are skipped, not written.** A column that is null for a row leaves that property as it was. If
  the user expects a null to clear a property, warehouse properties will not do it.

### 3. Propose the mapping before creating anything

Build the full `column_property_map` — `{warehouse_column: property_name}` — and show it to the user for
approval. Default to **the same name on both sides**; a rename is the user's call, not a guess worth making.

Exclude from the proposal, and say what you excluded:

- **The identifier column.** Its values identify the person, they do not describe them.
- **Anything `$`-prefixed, and `email`, `name`, `username`.** These are identity properties the SDKs set, and
  writing them from the warehouse can overwrite what PostHog already knows.
- **Columns that would be sensitive as a person property.** Password hashes, tokens, internal audit columns, and
  anything the user would not want visible in the person profile UI. Flag them rather than dropping them
  silently, since only the user knows their schema.

Then check collisions: read the existing person properties and call out any mapped name that already exists,
because the sync will overwrite it on every run. `custom-property-definitions-list` shows the warehouse
properties already configured, so you can also spot a table that is already mapped.

Wide tables are exactly when this matters — a twenty-column table proposed as a bare list is not reviewable.
Group the proposal into what will be mapped, what you excluded and why, and what collides.

### 4. Create it

Create the definition first, then the source:

1. `custom-property-definitions-create` with `target_type: person` (or `group` plus `group_type_index`),
   `display_type: text`, and a name describing the group of properties, not one column — the definition is the row
   the user sees in the UI. `display_type` is required by the API; use `text` for person and group targets, where it
   is ignored (it only drives how an account property renders, since profile properties are written as raw `$set` /
   `$group_set` values).
2. `custom-property-sources-create` with the definition id, exactly one of `external_data_schema` or
   `saved_query`, the whole `column_property_map`, and `key_column` set to the identifier from step 2.

The mapping and the binding are **create-only**. To change which columns are mapped, delete the property and
create it again — so it is worth getting the proposal right rather than iterating on a live mapping.

### 5. Backfill and verify

Creating an enabled source starts a backfill automatically. For an existing mapping, `custom-property-sources-backfill`
reads the whole table and populates historical rows; it coalesces if one is already running.

Then read `custom-property-sources-runs-list` and walk the funnel, which is where a mapping that "did nothing"
explains itself:

| Stage       | Zero here means                                                                  |
| ----------- | -------------------------------------------------------------------------------- |
| `rows_read` | Nothing was staged — the table has not synced since the mapping was created      |
| `changed`   | Every value already matches what was last sent; a re-run is expected to be quiet |
| `existing`  | No row's identifier matched a person or group — usually the wrong key column     |
| `produced`  | Nothing reached capture; check `skipped_missing_person`                          |

A run that reads rows but shows `existing: 0` is the wrong-key-column case almost every time.

## Notes that save a round trip

- The sync follows the **table's own schedule**. It is not separately schedulable, so "how often does this
  update" is answered by the table's sync frequency.
- A source that fails repeatedly is **disabled automatically** after five consecutive failures. Re-enabling it
  resets the streak and triggers a fresh backfill.
- "Sync now" runs the underlying table, which for a synced table is a real, billable warehouse sync, and for a
  materialized view is a materialization. It is not a cheap no-op — do not call it to "check" a mapping when
  `custom-property-sources-runs-list` answers the question for free.
