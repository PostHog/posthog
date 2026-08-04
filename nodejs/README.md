# PostHog Node.js services

Node.js services for PostHog: ingestion pipeline, CDP, session recording, and more.

## Testing CDP with Valkey Cluster locally

The development Compose stack includes a single-node Valkey instance with all 16,384 Redis Cluster slots assigned. Start it and run the focused tests with:

```bash
docker compose -f docker-compose.dev.yml up -d --wait valkey-cluster
pnpm --dir nodejs exec jest --runInBand --forceExit src/cdp/services/monitoring/hog-watcher.valkey.integration.test.ts
pnpm --dir nodejs exec jest --runInBand --forceExit src/cdp/services/monitoring/hog-watcher.service.test.ts
```

Containers discover slots through the announced Docker-network address. Host-side tests connect through `127.0.0.1:6390`.

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

Destructive test helpers refuse to run against a database without `test` in its name — see `tests/helpers/database-guard.ts`. The guard's error message explains how to fix a misconfigured environment.
