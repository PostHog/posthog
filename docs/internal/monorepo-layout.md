# Monorepo Layout

High-level structure of the PostHog monorepo. Some directories are aspirational (e.g., `platform/` doesn't exist yet - shared code currently lives in `common/`).

## Directory structure

```text
posthog/               # Legacy monolith code
  api/                 # DRF views, serializers
  models/              # Django models
  queries/             # HogQL query runners
  ...

ee/                    # Enterprise features (being migrated to products/ and posthog/)

products/              # Product-specific apps (see products/README.md for layout)
  <product>/
    backend/           # Django app (models, logic, api/, presentation/, tasks/, tests/)
    frontend/          # React (scenes, components, logics)
    manifest.tsx       # Routes, scenes, URLs
    package.json

services/              # Independent backend services
  llm-gateway/         # LLM proxy service
  mcp/                 # Model Context Protocol service
  oauth-proxy/         # OAuth proxy (Cloudflare Worker)
  stripe-app/          # Stripe integration app

common/                # Shared code (transitional - prefer other locations for new code)
  hogql_parser/        # HogQL parser

tools/                 # Developer/CI tooling, not imported by runtime code
  hogli/               # Developer CLI framework (PyPI-publishable; uv workspace member)
  hogli-commands/      # PostHog-specific hogli commands (consumed via hogli.yaml)

devenv/                # Developer environment config (intent map, process model)

platform/              # Shared platform code (aspirational - not yet created)
  integrations/        # External adapters
    vercel/
  auth/                # Token utils
  http/                # Shared HTTP clients
  storage/             # S3/GCS clients
  queue/               # Message queue helpers
  db/                  # Shared DB utilities
  observability/       # Logging, tracing, metrics
```

### Products

User-facing features with their own backend (Django app) and frontend (React). Examples: Feature Flags, Experiments, Session Replay.

- Vertical slices: each product owns its models, logic, API, and UI
- Isolated: products don't import each other's internals
- Turbo for selective testing, tach for import boundaries

See [products/README.md](/products/README.md) for how to create products. For new isolated products, see [products/architecture.md](/products/architecture.md) for design principles (DTOs, facades, isolation rules).

### Services

- are their own deployment
- have their own domain possibly
- have logic that doesn’t belong to any specific product
- aren’t shared infrastructure
- aren’t cross-cutting glue
- aren’t frontend-facing “products”

These are not glue, because glue adapts other systems.  
They are not products, because no one interacts with them as a user-facing feature.  
They are not platform, because they own domain logic, not shared tooling.

### Platform

Cross-cutting glue and infrastructure: external adapters (Vercel), clients, shared libs. Must not import products/services.

Why platform must not call product code:

- If platform imports and calls product code, platform becomes a hidden orchestrator
- it must know which products exist
- it must route events to product logic
- it accumulates product-specific conditionals
- dependency direction flips (platform → products)
- cycles become likely over time

That destroys the "platform is foundational" property and makes boundaries brittle.

### Common

Transitional bucket for shared code that exists today: `hogql_parser` and other cross-cutting utilities. New code should prefer `platform/`, `tools/`, `products/`, or `services/` — `common/` should not become the default dumping ground. Items here will migrate to more specific locations over time.

### Tools

Developer tooling: CLIs (notably `hogli/` framework + `hogli-commands/`), linters, formatters, code generators, scaffolding scripts, CI automation. Not imported by runtime code — build-time, CI, or developer-workflow artifacts only.

### Dev environment

Configuration for the local developer environment. The `devenv/` directory holds the intent/capability model that drives `hogli dev:setup` — mapping developer intents (e.g., "I'm working on error tracking") to capabilities (event_ingestion, replay_storage, etc.) and the processes that provide them. Process definitions live in `bin/mprocs.yaml`.
