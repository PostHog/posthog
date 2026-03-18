---
name: implementing-mcp-tools
description: 'Guide for exposing PostHog product endpoints as MCP tools. Use when creating new or updating API endpoints, adding MCP tool definitions, scaffolding YAML configs, or writing serializers with good descriptions. Covers the full pipeline from Django serializer to generated TypeScript tool handler.'
---

# Implementing MCP tools

Read the full guide at [docs/published/handbook/engineering/ai/implementing-mcp-tools.md](docs/published/handbook/engineering/ai/implementing-mcp-tools.md).

## Quick workflow

```sh
# 1. Scaffold a starter YAML with all operations disabled.
#    --product discovers endpoints via x-explicit-tags (priority 1) then
#    URL substring match (fallback). ViewSets in products/<name>/backend/
#    are auto-tagged. ViewSets elsewhere need @extend_schema(tags=["<product>"]).
pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
    --output ../../products/your_product/mcp/tools.yaml

# 2. Configure the YAML — enable tools, add scopes, annotations, descriptions
#    Place in products/<product>/mcp/*.yaml (preferred) or services/mcp/definitions/*.yaml

# 3. Add a HogQL system table in posthog/hogql/database/schema/system.py
#    and a model reference in products/posthog_ai/skills/query-examples/references/

# 4. Generate handlers and schemas
hogli build:openapi
```

## Before you scaffold: fix the backend first

The codegen pipeline can only generate correct tools if the Django backend exposes correct types.
Read the [type system guide](../../../docs/published/handbook/engineering/type-system.md) for the full picture.

Before scaffolding YAML, verify:

1. **Serializers have explicit field types and `help_text`** —
   these flow all the way to Zod `.describe()` in the generated tool.
   Missing descriptions = agents guessing at parameters.
   Use `ListField(child=serializers.CharField())` instead of bare `ListField()`,
   and `@extend_schema_field(PydanticModel)` on `JSONField` subclasses to get typed Zod output
   (see `posthog/api/alert.py` for the pattern).
2. **Plain `ViewSet` methods have `@extend_schema(request=...)`** —
   without it, drf-spectacular can't discover the request body
   and the generated tool gets `z.object({})` (zero parameters).
   `ModelViewSet` with a `serializer_class` is fine; plain `ViewSet` with manual validation is not.
3. **Query parameters use `@validated_request`** or `@extend_schema` with a query serializer —
   otherwise boolean and array query params may produce type mismatches in the generated code.

If a generated tool has an empty or wrong schema, the fix is almost always on the Django side,
not in the YAML config.
For a full audit checklist and before/after examples, use the `improving-drf-endpoints` skill.

## When to add MCP tools

When a product exposes API endpoints that agents should be able to call.
MCP tools are atomic capabilities (list, get, create, update, delete) — not workflows.

If you're adding a new endpoint, check whether it should be agent-accessible.
If yes, add a YAML definition and generate the tool.

## Tool design

Tools should be **basic capabilities** — atomic CRUD operations and simple actions.
Agents compose these primitives into higher-level workflows.

Good: "List feature flags", "Get experiment by ID", "Create a survey".
Bad: "Search for session recordings of an experiment" — bundles multiple concerns.

## YAML definitions

YAML files configure which operations are exposed as MCP tools.
See existing definitions for patterns:

- `products/<product>/mcp/*.yaml` — preferred, keeps config close to the code
- `services/mcp/definitions/*.yaml` — fallback for functionality without a product folder

The build pipeline discovers YAML files from both paths.

### Key fields

```yaml
category: Human readable name
feature: snake_case_name # should match the product folder name (used for runtime filtering)
url_prefix: /path # frontend app route, used for enrich_url links
tools:
  your-tool-name: # kebab-case
    operation: operationId_from_openapi
    enabled: true
    scopes:
      - your_product:read
    annotations:
      readOnly: true
      destructive: false
      idempotent: true
    # Optional:
    mcp_version: 1 # 2 for create/update/delete ops, 1 for read/list if available via HogQL
    title: List things
    description: >
      Human-friendly description for the LLM.
    list: true
    enrich_url: '{id}'
    param_overrides:
      name:
        description: Custom description for the LLM
```

Unknown keys are rejected at build time (Zod `.strict()`).

### Syncing after endpoint changes

```sh
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

Idempotent and non-destructive — adds new operations as `enabled: false`, removes stale ones.

## Serializer descriptions

Descriptions flow through the entire pipeline:

```text
Django serializer field → OpenAPI spec → Zod schema → MCP tool description
```

These descriptions are what agents read to understand tool parameters.

- Use `help_text` on serializer fields — it becomes the OpenAPI description.
- Use `param_overrides` in YAML to override generated descriptions with imperative instructions.
- Be specific about formats, constraints, and valid values.
- Avoid jargon that an LLM wouldn't understand without context.

## HogQL system tables

Every list/get endpoint should have a corresponding HogQL system table
in [`posthog/hogql/database/schema/system.py`](posthog/hogql/database/schema/system.py).
This lets agents query data via SQL in v2 of the MCP.

Each system table **must include a `team_id` column** for data isolation.

Use `mcp_version: 1` on read/list YAML tools when a system table covers the same data —
v2 agents use SQL instead.

When adding a system table, also add a model reference file
(`models-<domain>.md`) in [`products/posthog_ai/skills/query-examples/references/`](products/posthog_ai/skills/query-examples/references/)
and register it in [`products/posthog_ai/skills/query-examples/SKILL.md`](products/posthog_ai/skills/query-examples/SKILL.md) under **Data Schema**.

## Two MCP versions

- **v1 (legacy)**: all CRUD tools exposed, for clients without skill support.
- **v2 (SQL-first)**: read/list tools replaced by HogQL, create/update/delete tools kept. For coding agents.

Control per-tool availability with `mcp_version: 1/2` in the YAML definition.
