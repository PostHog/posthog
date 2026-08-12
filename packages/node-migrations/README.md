# PostHog Node.js migrations

`@posthog/node-migrations` provides the PostgreSQL migration contract for standalone Node.js services.

It provides:

- Ordered migration checks.
- A single transaction for each migration run.
- PostgreSQL advisory locking.
- A migration history table derived from the service name.
- Structured logging through `@posthog/node-service`.
- A shared `posthog-node-migrate` command.

## Service setup

Add the package as a workspace dependency and keep SQL files under the service root:

```text
migrations/
└── 0001_create_example.sql
```

SQL migrations use explicit up and down markers:

```sql
-- Up Migration
CREATE TABLE example (...);

-- Down Migration
DROP TABLE example;
```

Add package commands instead of a service-specific migration script:

```json
{
  "scripts": {
    "premigrate": "pnpm --filter=@posthog/node-service build && pnpm --filter=@posthog/node-migrations build",
    "migrate": "posthog-node-migrate --service example-service"
  }
}
```

Run migrations with an explicit database URL:

```bash
DATABASE_URL=postgres://... pnpm --filter=@posthog/example-service migrate
```

The service name must use lowercase letters, numbers, and hyphens. `example-service` records history in `example_service_schema_migrations`, which prevents migration history from colliding when services share a database. Applied migration checksums are verified so edited or deleted migration history fails before new SQL runs.

The shared command applies up migrations only. Correct production schema changes with a new forward migration rather than automatically rolling back an applied migration.

Use `--wait` only when migration jobs should wait for another migrator to finish. The default fails immediately when the advisory lock is held.

## Tests

The package integration suite uses the repository `test_posthog` database and verifies migration history, repeat runs, and checksum drift:

```bash
pnpm --filter=@posthog/node-migrations test:integration
```

## Ownership

Use this package only for tables owned by the Node.js service. Tables owned by Django continue to use Django migrations.

Application processes must not run migrations during startup. Run the migration command as a separate development, CI, or deployment step.
