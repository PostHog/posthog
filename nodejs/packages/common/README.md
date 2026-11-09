# @posthog/node-common

The library every PostHog Node service builds on: the logger, Postgres and Redis clients, the Kafka client and the outputs layer, team lookup, the personhog client, the generated proto stubs, and the domain types.

Ingestion owns and publishes it. The ingestion services use it from this workspace; the other Node services pin a version and move to a new one with a bump of their own.

## Shape

- `src/<area>/...` is importable as `@posthog/node-common/<area>/...`; `src/types.ts`, `src/config.ts`, `src/plugin-scaffold.ts` and `src/lifecycle.ts` as `@posthog/node-common/types` and so on.
- `src/testing/` holds the test helpers that need nothing but this package, published as `@posthog/node-common/testing/<name>`.
- `types.ts` carries the shared domain types and the `Hub` every service extends. A service defines its own `PluginsServerConfig` and `HubServices` on top of `CommonConfig` and the `HubServices` here, and re-exports the rest.
- `config/config.ts` reads the common settings from the environment. A service merges its own defaults with `overrideWithEnv`.
- Nothing here registers a Prometheus metric twice: a process loads exactly one copy of this package, so consumers must not copy its files.

## Commands

- `pnpm typescript:check`, `pnpm lint`, `pnpm format`
- `pnpm test` (needs the stack from `ingestion/ci/docker-compose.yml`)
- `pnpm build` writes `dist/`, which is what consumers resolve.
- `pnpm generate:personhog-proto` and `pnpm generate:ingestion-worker-proto` regenerate the stubs from `ingestion/proto`.
