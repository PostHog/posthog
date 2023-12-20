# rusty-hook
A reliable and performant webhook system for PostHog

## Requirements

1. [Rust](https://www.rust-lang.org/tools/install).
2. [Docker](https://docs.docker.com/engine/install/), or [podman](https://podman.io/docs/installation) and [podman-compose](https://github.com/containers/podman-compose#installation): To setup development stack.

## Testing

1. Start development stack:
```bash
docker compose -f docker-compose.yml up -d --wait
```

2. Test:
```bash
# Note that tests require a DATABASE_URL environment variable to be set, e.g.:
# export DATABASE_URL=postgres://posthog:posthog@localhost:15432/test_database
# But there is an .env file in the project root that should be used automatically.
cargo test
```
