# PostHog Node.js service runtime

`@posthog/node-service` provides the small runtime contract shared by standalone Node.js services.

It includes:

- A structured Pino logger.
- A service-owned Prometheus registry and standard HTTP metrics.
- Hono middleware for request IDs, security headers, metrics, logging, and errors.
- Liveness, readiness, and metrics endpoints.
- Graceful HTTP draining and shutdown hooks.
- Optional OpenTelemetry spans through `@opentelemetry/api`.

The OpenTelemetry API is safe to use without an SDK. Spans remain no-ops until the service configures an SDK and exporter before creating the app.

The package does not provide database clients, authentication, CORS policy, retries, or domain metrics.

## Create a service

```bash
bin/hogli service:bootstrap example-service
pnpm install
pnpm --filter=@posthog/example-service test
```

The generated service includes unit, integration, and end-to-end test layouts, test timing budgets, a production bundle, and a Docker build command. Shared package commands build the bundle and report test performance, so generated services do not carry custom build or reporting scripts.

Generated services use vertical feature slices:

```text
src/
├── index.ts
├── app.ts
├── config.ts
└── features/
    └── hello/
        ├── routes.ts
        ├── greeting.ts
        └── greeting.test.ts
```

Add external adapters under `src/infrastructure/` when needed. Avoid creating global controller, service, and repository layers before the service has behavior that needs them.

## Database ownership and migrations

Decide who owns a table before adding database code:

- Django-owned tables continue to use Django migrations.
- Service-owned tables use versioned migrations stored with that service.

Run service-owned migrations as an explicit development, CI, and deployment step. Application processes must not modify schemas during startup. PostgreSQL services can use [`@posthog/node-migrations`](/packages/node-migrations/README.md) for migration history, advisory locking, and the shared migration command.

## Shared service commands

The package exposes a standard build command. It bundles `src/index.ts` to `dist/server.mjs` by default:

```json
{
  "scripts": {
    "build": "posthog-node-service-build"
  }
}
```

Add named entries without creating a local build script:

```bash
posthog-node-service-build --entry migrate=@posthog/node-migrations/cli
```

The package also exposes `posthog-node-service-test-report`, which reads `test-results/*.xml` and `test-performance-budgets.json` from the service directory. `posthog-node-service-docker-build` infers the package name and service path, builds the shared Dockerfile, and tags the image from the package name.

## Runtime API

```ts
const service = createNodeService({
  name: 'example-service',
  readinessChecks: {
    postgres: async () => ({ status: 'ok' }),
  },
})

service.app.get('/api/example', (context) => context.json({ status: 'ok' }))

const started = await startNodeService({ service, port: 3000 })
started.addShutdownHook('postgres', () => pool.end())
```

Standard endpoints:

- `GET /_health`
- `GET /_ready`
- `GET /_metrics`

HTTP metric labels use Hono route templates. Do not replace them with raw request paths.

## Docker

Services with a bundled `dist/server.mjs` use the shared Docker command rather than maintaining one Dockerfile per service:

```bash
pnpm --filter=@posthog/example-service docker:build
```

Override the generated image tag when needed:

```bash
pnpm --filter=@posthog/example-service docker:build --tag custom-image
```

The shared builder also copies optional migration bundles and `migrations/` directories into the runtime image. Services that require system packages should use a specialized Dockerfile while preserving the same runtime entrypoint and probe contract.

A published PostHog base image is not required for this contract. The runtime stage already uses the repository-pinned Node slim image, while the shared Dockerfile keeps workspace pruning and bundling in one place. Introduce a published base image only when multiple services need the same additional operating-system packages or runtime configuration.

See [the follow-up adoption plan](./docs/follow-up-adoption.md) for the proposed agent proxy migration and the OAuth proxy runtime boundary.
