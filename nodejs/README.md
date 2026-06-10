# PostHog Node.js services

Node.js services for PostHog: ingestion pipeline, CDP, session recording, and more.

## Running tests

Tests run against **dedicated test databases**, never the dev stack's databases:

| Store                         | Test database                           | Dev database (never used by tests) |
| ----------------------------- | --------------------------------------- | ---------------------------------- |
| Postgres (common)             | `test_posthog`                          | `posthog`                          |
| Postgres (persons)            | `test_persons`                          | `posthog_persons`                  |
| Postgres (behavioral cohorts) | `test_behavioral_cohorts`               | `behavioral_cohorts`               |
| Postgres (cyclotron)          | `test_cyclotron`, `test_cyclotron_node` | `cyclotron`                        |
| ClickHouse                    | `posthog_test`                          | `default`                          |

These are the defaults whenever `NODE_ENV=test`, which `jest.setup-env.ts` forces for every jest run. The schema is owned by Django and rust migrations, so the test databases must be created before the first run:

```bash
# From the repo root, with the dev stack's Postgres/ClickHouse/Kafka/Redis running:
pnpm --filter=@posthog/nodejs setup:test
```

This runs Django's `setup_test_environment` (creates `test_posthog` and the ClickHouse `posthog_test` schema) plus the rust migrations for the persons, behavioral cohorts, and cyclotron test databases. Then:

```bash
cd nodejs
pnpm test                      # full suite (sharded in CI)
pnpm jest tests/path/to.test.ts  # single file
```

### Destructive helper guard

Test helpers like `resetTestDatabase()` and `clearDatabase()` delete all rows from most tables in the database they connect to. To protect local dev data, the helpers in `tests/helpers/sql.ts` and `tests/helpers/clickhouse.ts` verify (via Postgres `current_database()` / ClickHouse `currentDatabase()`) that the connected database has `test` in its name and refuse to run otherwise — see `tests/helpers/database-guard.ts`.

If your test database legitimately doesn't match (e.g. a custom CI setup), set `ALLOW_NON_TEST_DATABASE_RESET=1` (or `true`/`yes`) to bypass the guard; any other value keeps it active. Do not set this in a local dev environment.

If you hit the guard error locally, it means `DATABASE_URL`, `PERSONS_DATABASE_URL`, `CLICKHOUSE_DATABASE`, or similar leaked into the test process from your shell or IDE — unset them and rely on the test defaults.
