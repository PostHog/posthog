---
name: implementing-mcp-tools
description: 'Guide for exposing PostHog product endpoints as MCP tools. Use when creating new or updating API endpoints, adding MCP tool definitions, scaffolding YAML configs, or writing serializers with good descriptions. Covers the full pipeline from Django serializer to generated TypeScript tool handler.'
---

# Implementing MCP tools

Read the full guide at [docs/published/handbook/engineering/ai/implementing-mcp-tools.md](../../../docs/published/handbook/engineering/ai/implementing-mcp-tools.md).

## Quick workflow

```sh
# 1. Only for a product with no YAML yet: create one with no tools.
#    --product discovers endpoints via their x-product attribution.
#    ViewSets in products/<name>/backend/ are auto-attributed via module
#    path. ViewSets elsewhere need
#    @extend_schema(extensions={"x-product": "<product>"}).
pnpm --filter=@posthog/mcp run scaffold-yaml -- --product your_product \
    --output ../../products/your_product/mcp/tools.yaml

# 2. List the product's operations that have no YAML entry, then add the ones agents need.
#    --add writes an enabled entry; title and description come from the API unless the YAML sets them.
#    Add --file <path> to write to a YAML file other than the product's tools.yaml.
pnpm --filter=@posthog/mcp run scaffold-yaml -- --candidates --product your_product
pnpm --filter=@posthog/mcp run scaffold-yaml -- --add your_product_things_list --product your_product

# 3. Configure the entry — description, and annotations for PATCH/POST/PUT
#    (scopes come from the API when omitted)
#    Place in products/<product>/mcp/*.yaml (preferred) or services/mcp/definitions/*.yaml

# 4. Add a HogQL system table in posthog/hogql/database/schema/system.py
#    and a model reference in products/posthog_ai/skills/querying-posthog-data/references/

# 5. Generate handlers and schemas
hogli build:openapi

# 6. Refresh the tool input schema snapshots (CI unit tests fail on a stale snapshot)
pnpm --filter=@posthog/mcp exec vitest run tests/unit/tool-schema-snapshots.test.ts -u
# A tool behind a new `feature_flag` needs that flag in the test's `featureFlags` map, set to the value that shows the tool:
# true for a plain gate, the variant string for a variant gate, a non-true value for a `disable` gate.

# 7. Only when the YAML uses ui_apps: regenerate the UI apps (CI checks they are current)
pnpm --filter=@posthog/mcp run generate:ui-apps
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
   (see `products/alerts/backend/presentation/views/alert.py` for the pattern).
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

## Tool naming constraints

Tool names and feature identifiers are validated at build time and in CI.
Violations fail the build.

### Tool names

- **Format**: lowercase kebab-case — only `[a-z0-9-]`, no leading/trailing hyphens
- **Length**: 52 characters or fewer
- **Convention**: `domain-action`, e.g. `cohorts-create`, `dashboard-get`, `feature-flags-list`

#### Keep action verbs out of compact tool domains

The single-exec prompt builds its compact domain index with
`ToolDomainExtractor`. Large families can split at an intermediate segment.
Without action trimming, `experiment-freeze-exposure` can advertise the
redundant domain `experiment-freeze` instead of `experiment`.

Whenever you add or rename an action tool, check the
[`TRAILING_ACTIONS`](../../../services/mcp/src/lib/instructions.ts) set in the
same change. If a rendered domain can end in an operation verb that is not
already present, add the verb. Cover it in
`services/mcp/tests/unit/instructions.test.ts`. This applies even when the verb
is not the final segment of the full tool name.

Add operation verbs such as `freeze`, `publish`, or `emit`. Do not add resource
or capability nouns such as `config`, `logs`, `stats`, or `schedule` merely to
make the prompt shorter; those remain useful discovery domains.

### Feature identifiers

- **Format**: lowercase snake*case — only `[a-z0-9*]`, must start with a letter
- **Convention**: should match the product folder name, e.g. `error_tracking`, `feature_flags`

### Why 52 characters?

MCP clients enforce different limits on tool names. The 52-char limit is the safe zone
that works across all known clients:

| Client           | Limit                          | Notes                                                            |
| ---------------- | ------------------------------ | ---------------------------------------------------------------- |
| MCP spec (draft) | 1–128 chars, `[A-Za-z0-9_\-.]` | Official recommendation, not enforced                            |
| Claude Code      | 64 chars                       | Hard limit; prefixes tool names with `mcp____`                   |
| Cursor           | 60 chars combined              | `server_name + tool_name`; tools over this are silently filtered |
| OpenAI API       | `^[a-zA-Z0-9_-]+$`, 64 chars   | No dots allowed                                                  |

With the server name "posthog" (7 chars) plus a separator, tool names must stay at
or below 52 characters to fit within Cursor's 60-char combined limit.

### CI enforcement

- `pnpm --filter=@posthog/mcp lint-tool-names` — validates length and pattern for YAML and JSON definitions
- A vitest test validates all runtime `TOOL_MAP` and `GENERATED_TOOL_MAP` entries

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
    # Optional:
    scopes: # defaults to the scopes the API requires (from the OpenAPI spec)
      - your_product:read
    annotations: # defaults for GET and DELETE; required for PATCH, POST and PUT
      readOnly: true
      destructive: false
      idempotent: true
    title: List things
    description: >
      Human-friendly description for the LLM.
    list: true
    enrich_url: '{id}'
    param_overrides:
      name:
        description: Custom description for the LLM
    response: # filter response fields (applied per-item on list endpoints)
      include: [id, key, name] # keep only these fields (dot-path wildcards supported)
      exclude: [filters.groups.*.properties] # remove these fields
      # include and exclude are mutually exclusive
      selectable: true # add optional `fields` param so the agent picks a subset of `include` per call
      # (constrained to the allowlist); omit `fields` to return the full set. Requires `include`.
      strip_nulls: true # remove keys whose value is `null`, applied after include/exclude
      # Use it on tools that echo a nested serializer schema, where the unset optional fields
      # dominate the payload. Rejected with `list: true`, where per-row null removal makes the
      # TOON table larger. Use `exclude` to drop the fields on a list tool instead.
    feature_flag: my-flag-key # gate this tool behind a PostHog feature flag
    feature_flag_behavior: enable # 'enable' (default) or 'disable'
```

When `scopes` is omitted, the generator uses the scopes the API requires, so the tool cannot drift from the endpoint.
Set `scopes` by hand only when the API computes them per request (the generator fails and says so) or to gate a tool more tightly.
A `scopes` list that misses a scope the API requires fails codegen, with a GitHub annotation on CI.
When the API picks the scopes per request, list the action in the viewset's `request_dependent_scope_actions`.
The spec then marks the operation with `x-request-dependent-scopes`, codegen skips the check for it, and its tools must declare `scopes`.
`annotations` default to the HTTP method for GET (read-only) and DELETE (destructive).
PATCH, POST and PUT vary too much (a PATCH can be a soft delete or non-idempotent), so declare `annotations` for them.

When a tool needs custom logic around the request, set `hooks: <path under src/tools/>` and default-export an object with `beforeRequest`, `afterResponse` or `onError` from that module, written `export default { onError } satisfies ToolHooks<Params>` so a typo fails typecheck (see `ToolHooks` in `src/tools/tool-hooks.ts`).
Use it to read state before a write or to turn a known error into a result, rather than shadowing the generated tool with a hand-written one.

Unknown keys are rejected at build time (Zod `.strict()`).

### Gating tools with feature flags

Add `feature_flag` to any tool (standard or query wrapper) to gate its exposure on a PostHog feature flag evaluated at MCP init time for the current user.

- `feature_flag_behavior: enable` (default) — tool is shown **only when the flag is on**. Use for rolling out new tools.
- `feature_flag_behavior: disable` — tool is hidden **when the flag is on**. Use for sunsetting old tools.

Reusing the same flag key with both behaviors performs an atomic swap: flag on → new tool visible, old tool hidden; flag off → old tool visible, new tool hidden. Useful for A/B testing tool variations.

Flags are evaluated in parallel at init via `evaluateFeatureFlags`. If a flag can't be evaluated (service error, missing flag), `enable`-gated tools are excluded and `disable`-gated tools are included — fail-closed for new tools, fail-open for existing ones.

### Enabling or renaming a tool

The MCP server and Django deploy separately.
A tool that reaches clients before its route lands returns 404 on every call until the Django deploy catches up.
That hits a whole agent fleet at once.

- **Land the route first.** Ship the endpoint, then enable the tool in a later change. A tool with
  `enabled: true` in the same commit as a brand-new route is live in clients as soon as the MCP
  server deploys.
- **Or gate it.** Add `feature_flag` with `feature_flag_behavior: enable` and turn the flag on once
  the route is serving.
- **Keep the old name on a rename.** Leave the previous tool name in the YAML, pointing at the same
  operation, until the new name has deployed everywhere. Sunset it with
  `feature_flag_behavior: disable` on the same flag key, which swaps the two atomically.

### Deprecating a tool

A rename or a removal has two stages. Do not stop after the first one.

1. **Alias, while callers migrate.** Register the old name as a thin wrapper that calls the current
   handler and adds a `_deprecation_notice` to the response. The call still succeeds, and the agent
   learns the new name. See `services/mcp/src/tools/skills/deprecatedAliases.ts`, spread into
   `TOOL_MAP` in `services/mcp/src/tools/index.ts`. Use an alias only when the replacement accepts
   the same arguments.
2. **Redirect, when you delete the alias.** In the same change, add the old name to
   `DEPRECATED_TOOL_REDIRECTS` in `services/mcp/src/tools/exec.ts`. The call then fails with a
   `deprecated_tool` error that names the replacement, instead of the generic `Unknown tool: "..."`.
   State any argument changes in the text — see the `self-driving-inbox-get` entry.

Go directly to stage 2 when the replacement is not a drop-in. An alias that quietly drops renamed
parameters is worse than a call that fails.

Keep the redirect entry until the old name stops receiving traffic. `isRecordableToolName` records
`$mcp_exec_target_tool` only for a name the server owns: a live tool, or a
`DEPRECATED_TOOL_REDIRECTS` key. If you delete the entry too early, the remaining calls become
unattributable in MCP analytics, and you can no longer tell whether anything still uses the old name.

A tool that a feature flag removes is a different case. It keeps its definition, declares
`superseded_by` in the YAML, and `flagGatedToolMessage` answers the call.

### Keeping an operation off on purpose

Tools are opt-in: an operation without a YAML entry is not exposed, and nothing writes entries for new endpoints.
Write an entry with `enabled: false` only to record a decision, for example a tool superseded by another one.
Such an entry needs `disabled_reason: <why>`; codegen rejects `enabled: false` without it, and `disabled_reason` on an enabled tool.

### Syncing after endpoint changes

```sh
pnpm --filter=@posthog/mcp run scaffold-yaml -- --sync-all
```

Idempotent and never adds entries. It keeps every entry whose operation exists, updates renumbered `_N` operation IDs,
drops a disabled entry whose operation is gone, and fails on an enabled tool whose operation is gone.

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
in [`posthog/hogql/database/schema/system.py`](../../../posthog/hogql/database/schema/system.py).
This lets agents query data via SQL.

Each system table **must include a `team_id` column** for data isolation.

When adding a system table, also add a model reference file
(`models-<domain>.md`) in [`products/posthog_ai/skills/querying-posthog-data/references/`](../../../products/posthog_ai/skills/querying-posthog-data/references/)
and register it in [`products/posthog_ai/skills/querying-posthog-data/SKILL.md`](../../../products/posthog_ai/skills/querying-posthog-data/SKILL.md) under **Data Schema**.
