---
title: Implementing MCP tools
sidebar: Docs
showTitle: true
---

MCP tools are atomic capabilities – CRUD operations and simple actions that agents compose into workflows.
Every product should be accessible through the MCP server.
Tools answer "what can I do?" (list feature flags, execute SQL, create a survey).

For teaching agents _how_ to use these capabilities in combination,
see [Writing skills](/handbook/engineering/ai/writing-skills).

## TL;DR

```sh
# 1. Scaffold a starter YAML with all operations disabled
pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
    --output ../../products/your_product/mcp/tools.yaml

# 2. Configure the YAML – enable tools, add scopes, annotations, descriptions
#    Place in products/<product>/mcp/*.yaml (preferred, e.g. actions, cohorts)

# 3. Add a HogQL system table in posthog/hogql/database/schema/system.py
#    and a model reference in products/posthog_ai/skills/query-examples/references/

# 4. Generate handlers and schemas
hogli build:openapi

# 5. Merge to master – CI builds and distributes automatically
```

## Tool design principles

MCP tools should be **basic capabilities** – atomic CRUD operations and simple actions.
Agents compose these primitives into higher-level workflows.

**Good tools**:

- List feature flags
- Get an experiment by ID
- Create a survey
- Summarize a session recording

**Bad tools**:

- "Search for session recordings of an experiment" – this bundles multiple concerns.
  Instead, expose four composable tools:
  list experiments, get experiment, search session recordings, summarize sessions.

The reasoning: agents are better at composing simple tools than navigating complex ones,
and simple tools are reusable across many workflows.

## Two MCP server versions

Clients must support two main capabilities: MCPs and skills.
MCP support is widespread; however, skills support is still very early
and mostly coding agents support them.
To mitigate this, the MCP server ships two versions controlled via the
`x-posthog-mcp-version: <version_number>` header.

### Legacy MCP (v1)

For clients that don't support skills.
Exposes the full set of CRUD tools with simple instructions (list, read, create, update, delete).

Primarily oriented toward vibe-coding web tools.

### SQL-first MCP for clients supporting skills (v2)

v2 instructs the agent to read data through a unified HogQL interface
(list and get tools are generally excluded),
which unlocks flexibility in data retrieval, search, and manipulation.
Additionally, the consumer has access to a skill that provides schema references and example patterns,
giving it richer context about PostHog's data model.

Primarily oriented toward coding agents (PostHog Code, PostHog AI, Claude Code).

## SQL-first MCP: HogQL system tables

Every list/get endpoint exposed as an MCP tool must have a corresponding HogQL system table.
This lets agents query PostHog data via SQL in addition to (or instead of) the REST API tools.

System tables are defined in [`posthog/hogql/database/schema/system.py`](https://github.com/PostHog/posthog/blob/master/posthog/hogql/database/schema/system.py) as `PostgresTable` instances.
Each table must include a `team_id` column for data isolation.

Use `mcp_version: 1/2` to control availability of retrieval tools in v2 of the MCP.

Example from the codebase:

```python
feature_flags: PostgresTable = PostgresTable(
    name="feature_flags",
    postgres_table_name="posthog_featureflag",
    fields={
        "id": IntegerDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        # ...
    },
)
```

Agents query these tables with the `system.` prefix:

```sql
SELECT id, key, name FROM system.feature_flags WHERE active = 1 LIMIT 10
```

### Extending query examples

When you add a new system table,
also add a model reference file to [`products/posthog_ai/skills/query-examples/references/`](https://github.com/PostHog/posthog/tree/master/products/posthog_ai/skills/query-examples/references).
The naming convention is `models-<domain>.md`.

Existing references:

- `models-actions.md`
- `models-cohorts.md`
- `models-dashboards-insights.md`
- `models-data-warehouse.md`
- `models-error-tracking.md`
- `models-flags-experiments.md`
- `models-groups.md`
- `models-notebooks.md`
- `models-surveys.md`
- `models-variables.md`

Each file documents the table's columns, types, nullability, and notable structures (like JSON fields).
See [`models-flags-experiments.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/query-examples/references/models-flags-experiments.md) for a good example.
Register your new reference in [`products/posthog_ai/skills/query-examples/SKILL.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/query-examples/SKILL.md) under **Data Schema**.

## Code generation pipeline

The pipeline turns Django serializers into MCP tool handlers via OpenAPI.
Run the full pipeline with:

```sh
hogli build:openapi
```

### Pipeline steps

```text
build:openapi-schema     Django → OpenAPI JSON (frontend/tmp/openapi.json)
        │
        ▼
build:openapi-types      OpenAPI → TypeScript API types (frontend)
        │
        ▼
build:openapi-mcp        OpenAPI → Zod schemas for MCP (Orval)
        │
        ▼
build:openapi-mcp-tools  YAML definitions + Zod schemas → TypeScript tool handlers
```

### YAML definitions

YAML definitions are the configuration layer.
They live in **`products/<product>/mcp/*.yaml`**, keeping config close to the owning product's code.

> **Fallback path:** `services/mcp/definitions/*.yaml` is available for functionality that doesn't have a product folder.
> When a product folder exists, always place definitions there.

The build pipeline discovers YAML files from both paths.
Product teams own their definitions and control which operations are exposed as MCP tools.

**Workflow: scaffold, configure, generate.**

1. **Scaffold** a starter YAML with all operations disabled.
   `--product` is a **substring match** on URL paths —
   it selects every endpoint whose path contains `/<name>/`
   (hyphens are normalized to underscores before matching).
   The value doesn't have to be an exact product name;
   any string that appears as a path segment will work
   (e.g., `--product actions` matches `/api/projects/{project_id}/actions/`).

   ```sh
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product
   # or output directly into a product folder:
   pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
       --output ../../products/your_product/mcp/tools.yaml
   ```

2. **Configure** the YAML – enable tools, add scopes, annotations, and descriptions.
   Each YAML file has a top-level structure validated by Zod ([`scripts/yaml-config-schema.ts`](https://github.com/PostHog/posthog/blob/master/services/mcp/scripts/yaml-config-schema.ts)):

   Tool names follow a **`domain-action`** convention in kebab-case,
   e.g. `feature-flags-list`, `experiments-create`, `surveys-delete`.
   The domain groups related tools together and the action describes the operation.

   ```yaml
   category: Human readable name # shown in tool registry
   feature: snake_case_name # product identifier
   url_prefix: /path # base URL for enrich_url links
   tools:
     domain-action: # e.g. feature-flags-list, experiments-create
       operation: your_product_endpoint_list # must match an OpenAPI operationId
       enabled: true # false excludes from generation
       # --- required when enabled: ---
       scopes: # API scopes
         - your_product:read
       annotations:
         readOnly: true
         destructive: false
         idempotent: true
       # --- optional: ---
       mcp_version: 2 # 2 for create/update/delete operations or not available through SQL for retrieval, 1 for read/list if available via HogQL
       title: List things # human-friendly title (used in UI)
       description: > # instructions for the LLM
         Human-friendly description for the LLM.
       list: true # marks as a list endpoint
       enrich_url: '{id}' # appended to url_prefix for result URLs
       exclude_params: [field] # hide params from tool input
       include_params: [field] # whitelist params (excludes all others)
       param_overrides: # override Orval-generated param descriptions
         name:
           description: Custom description for the LLM
   ```

   Unknown keys are rejected at build time (Zod `.strict()`) to catch typos early.
   See [supported annotations](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations) for the full list.

3. **Generate** handlers and schemas:

   ```sh
   hogli build:openapi
   ```

### Keeping definitions in sync

When backend API endpoints change, sync the YAML definitions:

```sh
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

This is idempotent and non-destructive –
it only adds newly discovered operations (with `enabled: false`) and removes stale ones.
All hand-authored configuration is preserved.
CI runs this as a drift check.

See [`services/mcp/definitions/README.md`](https://github.com/PostHog/posthog/blob/master/services/mcp/definitions/README.md) for the full YAML schema reference (note: YAML definitions themselves now live in product folders)
and [`services/mcp/scripts/yaml-config-schema.ts`](https://github.com/PostHog/posthog/blob/master/services/mcp/scripts/yaml-config-schema.ts) for the Zod validation source.

## Testing

See [How to develop and test](/handbook/engineering/ai/implementation#how-to-develop-and-test)
for instructions on running the MCP server locally and verifying tools end-to-end.

## Serializer best practices

Descriptions flow through the entire pipeline:

```text
Django serializer field → OpenAPI spec → Zod schema → MCP tool description
```

Product teams should **type and describe** their serializer fields.
These descriptions are what agents read to understand tool parameters –
vague or missing descriptions lead to worse agent behavior.

See the [type system guide](/handbook/engineering/type-system) for the full backend → frontend pipeline,
including how to set up viewsets, serializers, and `@extend_schema` correctly.

**Tips:**

- Use `help_text` on serializer fields – it becomes the OpenAPI description.
  Be careful when using imperative language in `help_text`,
  as the same annotations are used in the API docs.
- Use `param_overrides` in YAML definitions to override Orval-generated descriptions.
  This is useful when you want to add imperative instructions for specific fields.
- Be specific about formats, constraints, and valid values.
- Avoid jargon that an LLM wouldn't understand without context.
- `ListField` and `JSONField` need explicit types —
  use `ListField(child=serializers.CharField())` instead of bare `ListField()`,
  and `@extend_schema_field(PydanticModel)` on `JSONField` subclasses
  (see `posthog/api/alert.py` for the pattern).
  Without this, Orval generates `z.unknown()`.
- Plain `ViewSet` methods that validate manually need `@extend_schema(request=YourSerializer)` —
  without it, drf-spectacular can't discover the request body
  and the generated tool gets an empty schema with zero parameters.
  `ModelViewSet` with `serializer_class` works automatically.

## HogQL query schemas (WIP)

[`frontend/src/queries/schema/schema-assistant-queries.ts`](https://github.com/PostHog/posthog/blob/master/frontend/src/queries/schema/schema-assistant-queries.ts) defines structured query types
for the AI assistant (trends, funnels, retention, etc.).

These schemas describe the shape of analytical queries with rich JSDoc comments
that help agents generate correct HogQL.
The cleaner and better-described these schemas are,
the better agents perform at query generation.

This is a work in progress –
the goal is to make it easier to generate HogQL queries from typed schemas
than from freeform SQL.
A `schema.json` integration into the codegen pipeline is planned.

## Agent skills that support the MCP server

- **`query-examples`** – HogQL query patterns, system model schemas, and available functions.
  Extend this skill to explain how agents should use your HogQL-exposed tables and queries.
  See [`products/posthog_ai/skills/query-examples/SKILL.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/query-examples/SKILL.md).
