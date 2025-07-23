# Cassandra Migrations

This directory contains Cassandra migrations for PostHog using `cassandra-migrate`.

## Setup

The migration system uses the following structure:
- `cassandra-migrate.json` - Main configuration file
- `cassandra-migrate.ci.json` - CI-specific configuration
- `migrations/` - Directory containing migration files

## Usage

### Local Development

```bash
# Run migrations
pnpm cassandra:migrate

# Create a new migration
pnpm cassandra:create

# Rollback last migration
pnpm cassandra:rollback
```

### CI/CD Environment

**Environment Variables:**
- `CASSANDRA_HOST` - Cassandra host (default: localhost)
- `CASSANDRA_PORT` - Cassandra port (default: 9042)
- `CASSANDRA_KEYSPACE` - Keyspace name (default: posthog)

### Migration Files

Migration files should be named with a sequential number and descriptive name:
- `001_create_keyspace.cql` - Initial keyspace creation
- `002_create_user_table.cql` - Create user table
- etc.

### Example CI Usage

```yaml
steps:
  - name: Run Cassandra Migrations
    run: |
      export CASSANDRA_HOST=cassandra
      export CASSANDRA_KEYSPACE=posthog
      cd plugin-server
      pnpm cassandra:migrate
```