# rusty-hook
A reliable and performant webhook system for PostHog

## Requirements

1. [Rust](https://www.rust-lang.org/tools/install).
2. [sqlx-cli](https://crates.io/crates/sqlx-cli): To setup database and run migrations.
3. [Docker](https://docs.docker.com/engine/install/) or [podman](https://podman.io/docs/installation) (and [podman-compose](https://github.com/containers/podman-compose#installation)): To setup testing services.

## Testing

1. Start a PostgreSQL instance:
```bash
docker compose -f docker-compose.yml up -d --wait
```

2. Prepare test database:
```bash
export DATABASE_URL=postgres://posthog:posthog@localhost:15432/test_database
sqlx database create
sqlx migrate run
```

3. Test:
```bash
cargo test
```
