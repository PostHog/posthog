# Duckling team-scoping + per-environment tables — implementation plan

## Context

From the thread (James / Eric, 2026-06-19): weatherstage's warehouse (`DuckgresServer`) was
provisioned org-scoped with **no `team_id`**, so there's no first-class record of which teams
belong to a given duckling. Today you'd have to infer it from `posthog_ducklakebackfill`, which is
"weird" — that's an enablement table, not a membership map.

Two distinct problems:

1. **No team↔duckling link.** `DuckgresServer` / `DuckLakeCatalog` are org-scoped (`team` FK kept
   nullable + deprecated). A duckling is shared by every team in the org, so the relationship is
   genuinely `1 org-duckling → n teams`. There is no model expressing that membership.
2. **Table-name collision across teams.** The Dagster backfill writes every team into the _same_
   `ducklake.posthog.events` (and `posthog.persons`) table in the org's catalog
   (`posthog/dags/events_backfill_to_duckling.py`, `EVENTS_TABLE_DDL` / `ensure_events_table_exists`
   / `register_file_with_duckling`). Two teams in one org both land in `posthog.events`,
   distinguished only by the `team_id` column. We want per-environment tables.

## Decisions already reached in the thread

- New Django model expressing `team → DuckgresServer` (many teams → one server). It becomes the home
  for future per-team duckling config, not just this fix.
- `team_id` should be a real relationship on ducklings (don't read a backfill model to learn membership).
- Going forward, backfills write to `events_<environment_name>` (and persons equiv), **not** `events`.
- Use the **environment (Team) name**, normalized + truncated — not the raw team_id (Eric floated
  team_id; James preferred env name). A `sanitize_ducklake_identifier` helper already exists.
- Name selection might move into the onboarding flow.

## Proposed implementation

### 1. New model `DuckgresServerTeam`

In `posthog/ducklake/models.py`:

- `server` → `ForeignKey(DuckgresServer, related_name="teams", on_delete=CASCADE)`.
- `team` → `OneToOneField(Team, related_name="duckgres_server_team")` — a team belongs to exactly one
  duckling; the OneToOne enforces it and gives the required `team_id`.
- `table_suffix` → `CharField` storing the normalized environment name used to build
  `events_<suffix>` / `persons_<suffix>`. **Persist it** (don't recompute from `team.name` each run)
  so table identity is stable if the env is later renamed, and so collisions are resolved once.
- Inherit `TeamScopedRootMixin` per `CLAUDE.md` (fail-closed IDOR; the model is tenant-data with a
  `team_id`). Add the model to the IDOR baseline/coverage as required.
- `Meta.db_table = "posthog_duckgresserverteam"`; unique on `team` (via OneToOne) and a
  `unique_together(server, table_suffix)` so two envs in the same duckling can't collide.
- Migration (`/django-migrations` skill — mandatory).

Re James's open question ("do we want `not null`, i.e. ≥1 team required?"): keep `team_id` **required
on the link row**, but allow a `DuckgresServer` to exist with zero linked teams transiently (right
after provision, before the first team is attached). The invariant "a duckling has ≥1 team" is better
enforced by the provisioning/onboarding flow than by a DB constraint that would break provisioning ordering.

### 2. Write the link at provision time (fix the actual bug)

- `DataWarehouseViewSet.provision` already has `self.team`
  (`products/data_warehouse/backend/api/data_warehouse.py:847`) but only forwards `organization_id`.
  Pass the team through to `managed_warehouse.provision(...)`.
- In `_persist_duckgres_server` (`products/data_warehouse/backend/api/managed_warehouse.py`) /
  `upsert_duckgres_server_for_org` (`posthog/ducklake/common.py`), after upserting the server, upsert
  a `DuckgresServerTeam` for the provisioning team, computing `table_suffix` (see §4). Keep it
  best-effort/idempotent like the existing server upsert.
- **Backfill existing rows:** data migration that, for every existing `DuckLakeBackfill` (and/or
  existing `DuckgresServer`), creates the `DuckgresServerTeam` link via `team → org → server` and a
  computed suffix. This directly repairs weatherstage and any other already-provisioned duckling.

### 3. Per-environment table naming in the Dagster backfill

`posthog/dags/events_backfill_to_duckling.py` currently hardcodes `posthog.events` / `posthog.persons`
in many places. Parametrize the table name by the team's `table_suffix`:

- Add `events_table` / `persons_table` to `DucklingTarget`; resolve the suffix in
  `_resolve_duckling_target` (look up `DuckgresServerTeam` by team_id).
- Thread the table name through: `EVENTS_TABLE_DDL` / `PERSONS_TABLE_DDL` (already `.format()`-templated),
  `ensure_events_table_exists` / `ensure_persons_table_exists`, `table_exists`, `_set_table_partitioning`,
  `delete_events_partition_data` / `delete_persons_partition_data`, `validate_duckling_schema` /
  `validate_duckling_persons_schema`, the `DROP TABLE` paths, and the `ducklake_add_data_files`
  `'events'` / `'persons'` table argument in `register_file_with_duckling` /
  `register_persons_file_with_duckling`.
- Reuse `_validate_identifier` on the suffix before interpolation (it's already SQL-interpolated, not
  parameterized — keep that safe).

### 4. Environment-name normalization

- Use the existing `sanitize_ducklake_identifier(team.name, default_prefix="events")` from
  `posthog/ducklake/common.py` (lowercase, alnum+underscore, leading-digit guard, 63-char truncate).
- Build the suffix once at link creation; resolve in-org collisions deterministically (e.g. append
  `_<team_id>` when `unique_together(server, table_suffix)` would be violated). The thread floated a
  tiny model (Haiku) to pick a nicer name — treat that as a later enhancement, not required for correctness.
- Optionally surface/confirm the name during the managed-warehouse onboarding flow (James's last message).

### 5. Tests

- Model + migration tests (link creation, uniqueness, suffix collision).
- Provision path creates the link with the right suffix (extend
  `products/data_warehouse/backend/.../test` around `_persist_duckgres_server`).
- Dagster backfill: parametrized test that two teams in one org write to distinct
  `events_<a>` / `events_<b>` tables (extend `posthog/dags/test_events_backfill_to_duckling.py`).
- Data-migration test: existing `DuckLakeBackfill` rows produce correct links.

## Decisions to confirm before building

1. **Existing data migration.** Already-provisioned ducklings have data in plain `posthog.events`.
   Options: (a) leave old tables, only new writes go to `events_<suffix>` (risks split data for a
   team mid-flight); (b) one-time rename `events` → `events_<suffix>` for single-team ducklings as
   part of the backfill migration. (b) is cleaner where a duckling currently has exactly one team.
2. **Collision policy** for two environments with identical normalized names in one org — suffix with
   `_<team_id>`, or fail and require a manual name? Recommend auto-suffix.
3. **Onboarding scope** — is renaming/choosing the env name in the onboarding flow in scope for this
   change, or a fast-follow?

## Files touched (summary)

- `posthog/ducklake/models.py` — new `DuckgresServerTeam`.
- `posthog/migrations/` — schema migration + data backfill migration.
- `posthog/ducklake/common.py` — link upsert helper + suffix resolution.
- `products/data_warehouse/backend/api/managed_warehouse.py` + `.../data_warehouse.py` — create link at provision.
- `posthog/dags/events_backfill_to_duckling.py` — per-env table naming throughout.
- IDOR baseline / `.github/scripts/check-idor-model-coverage.py` coverage for the new model.
- Tests across the above.
