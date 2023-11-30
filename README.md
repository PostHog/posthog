# rusty-hook
A reliable and performant webhook system for PostHog

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
