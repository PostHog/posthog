# Monorepo Layout

High-level structure of the PostHog monorepo.

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
    services/          # Optional: services this product deploys (see "What a product can own")
    packages/          # Optional: libraries/CLIs this product owns

services/              # Independent services NOT owned by any one product
  llm-gateway/         # LLM proxy service
  mcp/                 # Model Context Protocol service
  oauth-proxy/         # OAuth proxy (Cloudflare Worker)
  stripe-app/          # Stripe integration app

packages/              # Libraries shared across more than one product/service (e.g. quill)

common/                # Shared code — holding pen, NOT a destination (goal: shrink it)
  hogql_parser/        # HogQL parser

tools/                 # Developer/CI tooling, not imported by runtime code
  hogli/               # Developer CLI framework (PyPI-publishable; uv workspace member)
  hogli-commands/      # PostHog-specific hogli commands (consumed via hogli.yaml)

devenv/                # Developer environment config (intent map, process model)
```

### Products

User-facing features with their own backend (Django app) and frontend (React). Examples: Feature Flags, Experiments, Session Replay.

- Vertical slices: each product owns its models, logic, API, and UI
- Isolated: products don't import each other's internals
- Turbo for selective testing, tach for import boundaries

See [products/README.md](/products/README.md) for how to create products. For new isolated products, see [products/architecture.md](/products/architecture.md) for design principles (DTOs, facades, isolation rules).

#### What a product can own

Most products are a Django app plus React scenes — and most already carry more: an `mcp/` directory of MCP tool definitions, often a `skills/` directory of agent skills. A product can own anything attributable to it, runtime and tooling alike. Nest it under the product instead of scattering it across top-level dirs:

- `products/<product>/mcp/` — MCP tool definitions (`tools.yaml`) and UI apps (most products)
- `products/<product>/skills/` — agent skills for the product (many products)
- `products/<product>/services/<svc>/` — a service or worker the product deploys
- `products/<product>/packages/<lib>/` — a library or CLI the product owns
- dev/CI/backfill scripts, benchmarks, audits, fixtures and dummy-data generators, a standalone console — same idea

Top-level `services/`, `packages/`, `tools/`, and `cli/` are for things no single product owns. Keep package names (`@posthog/<name>`) independent of location — pnpm resolves by name, so relocating later is a path move with no import churn.

Nest because tooling boundaries become path-scoped (`products/<product>/**` for CODEOWNERS, CI filters, lint) instead of hand-synced `<product>-*` prefixes. A prefix doing a folder's job is the signal to nest.

### Packages

This covers **pnpm workspace packages** (JS/TS). Python and Rust differ — there, location and import name matter directly (a top-level Python package can even shadow a stdlib module, which is why there's no top-level `platform/`), so these rules don't apply.

For pnpm packages, location doesn't gate who can import them (pnpm resolves by name), so location is an ownership signal, not access control. Place by current ownership:

- Owned by one product → `products/<product>/packages/<name>/` (the default — keeps the product self-contained).
- Genuinely shared across more than one product/service → top-level `packages/<name>/` (e.g. `packages/quill/`).
- Promote nested → root only when a second consumer actually depends on it — on real usage, not intent. It's a path rename with a stable package name (no import churn), so don't pay the "shared" cost before it's true.

`pnpm-workspace.yaml` globs are explicit (`products/*`, `packages/quill`, …) and don't yet match nested `products/<product>/packages/*` or a new top-level `packages/<name>/` — so register the package's path there when you add it, or `workspace:*` deps, filters, and scripts won't resolve.

### Services

- are their own deployment
- have their own domain possibly
- have logic that doesn’t belong to any specific product
- aren’t shared infrastructure
- aren’t cross-cutting glue
- aren’t frontend-facing “products”

These are not glue, because glue adapts other systems.
They are not products, because no one interacts with them as a user-facing feature.

### Common

A holding pen for shared code that predates a better home (`hogql_parser` and other cross-cutting utilities) — **not** a destination, and the goal is to shrink it, not grow it.

A catch-all "common" reliably rots into a junk drawer: unscoped, unenforced, imported by everything — a second monolith with worse boundaries than the first. The name itself is the smell; context-named homes are the cure. Unlike `products/*` (tach + turbo), nothing mechanically guards what lands here — only the convention, and conventions erode unless they're made hard to violate.

So new code should go somewhere with a real boundary first: `products/<name>/`, `tools/`, `services/`, or `packages/` (a clean, published-style leaf — `packages/quill` is the model). Land code in `common/` only when none of those fit _and_ it can't yet be a clean leaf because it still imports app modules (`lib/*`, `scenes/*`); when that's the case, treat it as tracked debt and name the graduation target. Once something here becomes a clean leaf, promote it out to `packages/` or the owning product and delete it from `common/`. See `common/AGENTS.md` for the agent-facing rules.

### Tools

Developer tooling: CLIs (notably `hogli/` framework + `hogli-commands/`), linters, formatters, code generators, scaffolding scripts, CI automation. Not imported by runtime code — build-time, CI, or developer-workflow artifacts only.

### Dev environment

Configuration for the local developer environment. The `devenv/` directory holds the intent/capability model that drives `hogli dev:setup` — mapping developer intents (e.g., "I'm working on error tracking") to capabilities (event_ingestion, replay_storage, etc.) and the processes that provide them. Process definitions live in `bin/mprocs.yaml`.
