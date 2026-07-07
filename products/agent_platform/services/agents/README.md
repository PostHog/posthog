# `@posthog/agents-image`

Build glue for the unified `posthog-agents` container image. **Not a
runtime package** — this directory exists only to host the Dockerfile,
the esbuild entrypoint script, and the tiny package.json that pulls the
three runtime workspaces into one bundle.

The image bakes three entrypoints into one slim Node 24 image:

| Service         | Command                                 | Default port |
| --------------- | --------------------------------------- | ------------ |
| `agent-ingress` | `node services/agents/dist/ingress.mjs` | 8080         |
| `agent-runner`  | `node services/agents/dist/runner.mjs`  | —            |
| `agent-janitor` | `node services/agents/dist/janitor.mjs` | 8082         |

Why one image: ingress + runner + janitor co-evolve (one DB schema, one
`@posthog/agent-shared`). The deploy manifest picks the entrypoint per
replica / Job, so bumping a SHA rolls all three in lockstep. Schema is
Django-owned (the `agent_platform` product DB) and applied by the
`migrate_product_databases` job — not by this image. (The console UI is a
separate product and lives in the posthog/code repo, not here.)

## Local

```bash
docker build -f services/agents/Dockerfile -t posthog-agents:dev .

# Long-running services
docker run --rm -e POSTHOG_DB_URL=... -e AGENT_DB_URL=... -p 8080:8080 \
    posthog-agents:dev node services/agents/dist/ingress.mjs
```

## Layout in the runtime image

```text
/code/services/agents/dist/{ingress,runner,janitor}.mjs
/code/services/agents/node_modules/              # pnpm symlinks for externals
/code/node_modules/.pnpm/                        # backing store (incl. node-rdkafka)
```

Bundles sit inside `services/agents/` so Node's module resolution finds
`services/agents/node_modules/node-rdkafka` (a pnpm symlink) when
`KafkaLogSink` does `await import('node-rdkafka')` at runtime. The bundle
declares `node-rdkafka` and `pg-native` as esbuild externals — they
cannot be inlined into a `.mjs` (`.node` addon for the former, optional
C addon for the latter), so they're loaded from `node_modules` at boot.
