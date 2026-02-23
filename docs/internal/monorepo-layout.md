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

products/              # Product-specific apps
  <product>/
    backend/           # Django app (models, logic, api/, presentation/)
    frontend/          # React (scenes, components, logics)
    manifest.tsx       # Routes, scenes, URLs
    package.json

services/              # Independent backend services
  llm-gateway/         # LLM proxy service
  mcp/                 # Model Context Protocol service

common/                # Shared code (exists today)
  hogli/               # Developer CLI tooling
  hogql_parser/        # HogQL parser

platform/              # Shared platform code (aspirational - not yet created)
  integrations/        # External adapters
    vercel/
  schemas/             # Shared Pydantic schemas
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

Shared code that exists today: `hogli` (developer CLI), `hogql_parser`, and other cross-cutting utilities. Some of this may eventually move to `platform/` or `tools/` as the structure matures.

### Tools (aspirational)

Developer tooling: CLIs, linters, formatters, code generators, scaffolding scripts. Not imported by runtime code. Can be standalone packages or internal utilities. Currently `tools/hogli/` (framework) and `common/posthog_hogli/` (PostHog command extensions) serve this purpose.
