# AI observability

AI observability started as an analytics view over generation events and
has grown into a full LLM platform: traces, evaluations, clustering,
prompt management, a model gateway, a playground, and review queues.

This README is the orientation map for the product folder. Agents
should also read [AGENTS.md](./AGENTS.md) for product-specific rules.

## Directory layout

```txt
products/ai_observability/
  backend/                # Django app (label: llm_analytics)
    presentation/views/   # Thin DRF viewsets that call the facade
    facade/               # Public entry points (api.py) and contracts
    logic/                # Behavior and data access, one folder per concept
    temporal/             # Temporal workflows and activities
    api/                  # Older DRF viewsets (one file per resource;
                          # api/__init__.py is the canonical inventory)
    llm/                  # Unified LLM client
      client.py           # Single entry point for provider calls
      providers/          # Per-provider adapters
      formatters/         # Provider request/response formatters
    models/               # Django models + pydantic validators
    migrations/
    queries/              # Raw .sql files used by query runners
    summarization/        # Trace and evaluation summarization
    translation/
    text_repr/            # Text-representation formatters for events
    tools/                # Shared backend tools
    test/                 # Tests for the older code
    tests/                # Tests for the layered code, one folder per layer
  frontend/               # React + kea
    redesign/             # Layered frontend: logics, hosts, components
    components/           # Reusable UI
    <feature>/            # clusters, datasets, evaluations, playground,
                          # prompts, settings, traceReviews,
                          # scoreDefinitions, skills, ...
    generated/            # Generated types (do not edit)
  mcp/                    # MCP tool definitions
  skills/                 # Agent skills scoped to the product
  docs/                   # Product decision records (created with the first one)
  shared/                 # Constants and schemas shared across frontend, backend, capture and ingestion (crosslang/)
  manifest.tsx            # Scene + navigation registration
  package.json            # Turborepo package (@posthog/products-ai-observability)
```

Query runners for the product live **outside** this folder in
`posthog/hogql_queries/ai/`. Three runners matter: `trace_query_runner.py`
(single trace), `traces_query_runner.py` (list), and
`session_query_runner.py` (traces in a session). See
[AGENTS.md](./AGENTS.md) for why that detail matters.

## Running tests locally

```bash
# Backend (pytest, Django)
hogli test products/ai_observability/backend
hogli test products/ai_observability/backend/api/test/test_trace_reviews.py

# HogQL query runners (live in posthog/, not products/)
hogli test posthog/hogql_queries/ai

# Frontend (Jest)
hogli test products/ai_observability/frontend
hogli test products/ai_observability/frontend/utils.test.ts --watch
```

After changing a serializer or viewset, regenerate OpenAPI and
TypeScript types:

```bash
hogli build:openapi
```

## Further reading

- [AGENTS.md](./AGENTS.md) — product-specific conventions.
- [products/architecture.md](../architecture.md) — target architecture for products (facades, contracts, isolation). [AGENTS.md](./AGENTS.md) says which parts of this product follow it.
