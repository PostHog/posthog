---
name: querying-local-postgres
description: Run read-only SQL against the local Postgres app database (SELECT, EXPLAIN, EXPLAIN ANALYZE on SELECT). Default local URL postgres://posthog:posthog@localhost:5432/posthog; else DATABASE_URL. Use when querying the local DB, inspecting tables, debugging data, or analyzing query plans. Mutations are strictly forbidden.
allowed-tools: Bash
---

# Querying local Postgres (READ-ONLY) — PostHog repo

User's query: $ARGUMENTS

**Scope:** This repo uses **PostgreSQL** for app metadata (teams, projects, flags, Django models, etc.). **Analytics event data** lives in **ClickHouse**, not Postgres — use HogQL / ClickHouse tools for `events`-style questions unless the user explicitly wants Postgres.

## When to use

- User asks to query the database, inspect tables, or run SQL against **Postgres**
- **Debugging**: Row-level checks (e.g. why a team/project/flag row looks wrong), migrations, constraints, duplicate keys
- **Performance**: `EXPLAIN` / `EXPLAIN (ANALYZE, …)` on **read-only `SELECT`** against Django or app tables

## Instructions

1. **Strictly forbid mutations** — See "Mutations strictly forbidden" below. If the user asks for any write or mutation, refuse and explain the skill is read-only.
2. **Translate** the user's question into one or more read-only SQL statements.
3. **Show the SQL** in a code block before running.
4. **Run** using the command pattern below (always with `PGOPTIONS='-c default_transaction_read_only=on'` to force a read-only connection).
5. **Show results** and give a brief interpretation (especially when used for debugging or plan review).

## Mutations strictly forbidden

**Do not run, suggest, or generate any of the following.** Refuse and state that this skill is read-only.

- **DML**: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `TRUNCATE`
- **DDL**: `CREATE`, `DROP`, `ALTER`, `RENAME`
- **Other writes**: `COPY ... TO program`, `CALL` (if it mutates), `GRANT`/`REVOKE`
- **`EXPLAIN ANALYZE` on anything other than a read-only `SELECT`** (including `WITH … SELECT`). Do not wrap DML in `EXPLAIN ANALYZE` — it would execute the write. The read-only connection below rejects writes, but the agent must not attempt this pattern.
- Any statement that modifies data, schema, or roles

**Allowed:**

- `SELECT` (including `WITH … SELECT`)
- `EXPLAIN` … `SELECT` (estimate-only plan; no execution)
- `EXPLAIN (ANALYZE, …) SELECT` — **executes** the `SELECT` once; use only for performance analysis. Must run on the read-only connection below.
- `SHOW`, `SELECT` from catalog views (`pg_stat_*`, `information_schema`, etc.) when read-only

If the user requests a write operation, say: "This skill is read-only. I can't run INSERT/UPDATE/DELETE or other mutations. Use a DB client or migration tool for writes."

## EXPLAIN and EXPLAIN ANALYZE (performance)

| Goal                                      | What to use                                                                     |
| ----------------------------------------- | ------------------------------------------------------------------------------- |
| Plan shape, estimated costs, no execution | `EXPLAIN (FORMAT TEXT, COSTS)` or add `VERBOSE`                                 |
| Actual timings, row counts, buffer hits   | `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)` on the **`SELECT`**                   |
| Buffer + WAL stats                        | `BUFFERS` requires **`ANALYZE`**; `WAL` requires **`ANALYZE`** (PostgreSQL 13+) |

**Safe pattern:** the analyzed statement must be **only** a `SELECT` (or `WITH … SELECT`), run on the read-only connection (see Usage below). Example:

```bash
PGOPTIONS='-c default_transaction_read_only=on' psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT)
SELECT … LIMIT 100;"
```

Optional flags (when useful): `SETTINGS` (show non-default GUCs), `WAL` (with `ANALYZE`), `TIMING` (default on in recent versions for `ANALYZE`).

**Caveats:**

- **`EXPLAIN ANALYZE` runs the query** — can be slow or heavy on large scans; prefer a bounded `SELECT` (e.g. realistic `WHERE`, `LIMIT` matching production shape) when exploring.
- **Production / shared DBs** — analyzing hot or wide queries can add load; prefer staging, a replica, or off-peak when the user cares about impact.
- **`EXPLAIN` without `ANALYZE`** — does not execute the inner statement (except some special cases); still only wrap **read-only** SQL.

## PostHog: connection and `DATABASE_URL`

### Local Postgres (host machine) — default for this skill

Use this **hardcoded** URL for day-to-day local queries (matches typical Docker Compose + port `5432` on localhost, SSL off):

| Setting  | Value       |
| -------- | ----------- |
| Host     | `localhost` |
| Port     | `5432`      |
| User     | `posthog`   |
| Password | `posthog`   |
| Database | `posthog`   |
| SSL      | off         |

```bash
# Prefer this unless the user says their local password/db differs
LOCAL_POSTGRES_URL='postgres://posthog:posthog@localhost:5432/posthog'
```

Equivalent: `postgresql://posthog:posthog@localhost:5432/posthog`

**Other local DBs** on the same server: swap the path only, e.g. `...5432/posthog_persons`.

---

**Configuration source of truth (app):** `posthog/settings/data_stores.py` (Django `DATABASES`, optional replica `POSTHOG_POSTGRES_READ_HOST`, direct `POSTHOG_POSTGRES_DIRECT_HOST`, `PERSONS_DB_WRITER_URL`, product DB routing from `products/db_routing.yaml`).

**When not using the hardcoded URL:** Connecting **from the host** with the same credentials is documented in [Developing locally](../../../docs/published/handbook/engineering/developing-locally.md) (`fe_sendauth` troubleshooting). Ensure containers are running.

**Default env when `DEBUG` is on:** Django builds a default `DATABASE_URL` from `PGHOST` (default **`db`**), `PGUSER` / `PGPASSWORD`, `PGPORT`, `PGDATABASE` — matching **in-container** hostnames. From the **host**, use `localhost` and the same user/password/database name unless your shell already exports `DATABASE_URL`.

**Multiple PostgreSQL databases** (same server in local compose; separate logical DBs):

- Main app DB: usually `posthog`
- Persons DB: `posthog_persons` (`PERSONS_DB_WRITER_URL` / `PERSONS_DB_READER_URL`)
- Product-isolated DBs: `posthog_<name>` per `products/db_routing.yaml` (created by `docker/postgres-init-scripts/create-product-dbs.sh`)
- Other init scripts may create additional DBs (e.g. cyclotron) — inspect `docker/postgres-init-scripts/` if needed

Point `psql` at the right database by changing the path in `DATABASE_URL` (e.g. `.../posthog_persons`).

**Rust / sqlx:** Some services use `rust/.env` for `DATABASE_URL` when working from `posthog/rust` — see `rust/README.md`.

## Usage (command pattern)

**Always** force the connection read-only via `PGOPTIONS='-c default_transaction_read_only=on'` so Postgres rejects writes even if the generated SQL is wrong.

> **Why `PGOPTIONS`, not `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`?**
> A `psql -c "..."` string with multiple statements runs as a **single implicit transaction**.
> `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` only sets the default for _subsequent_
> transactions — the in-progress one keeps the read-write mode it was given at `BEGIN`, so a write
> in the same `-c` would **not** be rejected. `PGOPTIONS='-c default_transaction_read_only=on'` sets
> the GUC at connection startup, so every transaction (including the implicit `-c` one) starts
> read-only. The inline equivalent is `SET TRANSACTION READ ONLY;` **as the first statement** of the
> `-c` string (it affects the current transaction, unlike `SET SESSION CHARACTERISTICS`).

**Run from the PostHog repo root** so relative env paths resolve.

**Default — local hardcoded URL** (`posthog` / `posthog` @ `localhost:5432` / db `posthog`):

```bash
PGOPTIONS='-c default_transaction_read_only=on' psql "postgres://posthog:posthog@localhost:5432/posthog" -v ON_ERROR_STOP=1 -c "SELECT 1;"
```

**Option A — `DATABASE_URL` already in the shell** (e.g. after `flox activate` or manual `export`):

```bash
PGOPTIONS='-c default_transaction_read_only=on' psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT 1;"
```

**Option B — load from a gitignored env file at repo root** (if `DATABASE_URL` is set there):

```bash
npx dotenv -e .env -- bash -c "PGOPTIONS='-c default_transaction_read_only=on' psql \"\$DATABASE_URL\" -c 'SELECT ...'"
```

- Use single quotes for string literals in SQL inside the shell as usual; escape carefully when nesting quotes in `-c`.
- Default `LIMIT 100` unless the user specifies otherwise.
- For wide rows use `-x`: `psql ... -x -c "..."`.

## Schema reference (PostHog)

- **Django models → tables:** see `posthog/models/` (and product packages under `products/`). Table names are usually prefixed with `posthog_` and snake-cased (e.g. `posthog_team`, `posthog_user`). Confirm with `\dt posthog_*` in psql, or check the model's `Meta.db_table` if nonstandard.
- **Migrations:** `posthog/migrations/` (and product migration paths) define the authoritative DDL over time.
- **Person table name:** configurable via `PERSON_TABLE_NAME` (see `data_stores.py`); default `posthog_person`.

## Debugging with the query runner (PostHog-flavored)

- Confirm a row exists for a team, project, user, or feature-flag linkage; check soft-delete / `deleted` fields where applicable.
- Compare counts and joins to what the app assumes (e.g. membership, project access).
- Validate replica vs primary read differences only if the user is connected to the right host (replica: `POSTHOG_POSTGRES_READ_HOST`).
- Use `EXPLAIN ANALYZE` on `SELECT` for slow Django queries **replicated as SQL** — mind loading production-sized data.

## Cross-reference

- Local setup and DB gotchas: `docs/published/handbook/engineering/developing-locally.md`
- Repo CLI: `hogli` (see `.agents/skills/hogli/SKILL.md`)
