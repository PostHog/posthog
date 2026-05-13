# MCP relevance heuristics

How to determine whether a PR diff affects MCP tool behavior.
The interpretation is generous — when in doubt, include it.

## The tool chain

Every MCP tool follows this chain from definition to execution:

```text
tools.yaml (operationId)
  → OpenAPI spec (path + method)
    → Django view/viewset (request handling)
      → serializer (validation + response shaping)
        → model (data layer)
          → business logic (domain rules, side effects)
```

A change to **any link** in this chain for any enabled tool is MCP-relevant.

## File pattern mapping

### Direct relevance (always generate scenarios)

| Pattern                           | What it means                                                 |
| --------------------------------- | ------------------------------------------------------------- |
| `products/*/mcp/tools.yaml`       | Tool definition changed — schema, description, params, scopes |
| `services/mcp/definitions/*.yaml` | Legacy tool definitions changed                               |
| `services/mcp/src/tools/`         | Tool handlers, registration, exec logic                       |
| `services/mcp/src/api/`           | MCP API client, request routing                               |
| `services/mcp/src/schema/`        | Schema validation, transforms, casting                        |
| `services/mcp/src/mcp.ts`         | MCP server initialization and registration                    |

### Indirect relevance (trace to confirm, then generate)

| Pattern                                     | How to confirm                                                                   |
| ------------------------------------------- | -------------------------------------------------------------------------------- |
| `products/*/backend/api/` or `posthog/api/` | Check if the changed viewset has an `operationId` referenced in any `tools.yaml` |
| Serializer files                            | Check if the serializer is used by a view backing an MCP tool                    |
| Model files                                 | Check if the model is used by a serializer/view backing an MCP tool              |
| `ee/hogai/`                                 | Agent behavior changes affect how tools are used in conversation                 |
| Query runners (`posthog/hogql/`)            | Affects `execute-sql` and query wrapper tools                                    |
| Permission/access control changes           | Could break tool authorization                                                   |
| `posthog/api/mixins.py`                     | Shared view mixins used by tool-backing views                                    |

### Tracing from changed file to affected tools

1. **Identify the changed file's role** — is it a model, serializer, view, or business logic?

2. **Find the view** — if the change is in a model or serializer, find which view uses it:

   ```bash
   grep -r "ClassName" products/*/backend/api/ posthog/api/ --include="*.py" -l
   ```

3. **Find the operationId** — check the view's URL pattern name or `@action` decorator.
   The operationId format is typically `{url_name}_{action}` (e.g., `feature_flags_create`).

4. **Find the tool** — search tools.yaml files for that operationId:

   ```bash
   grep -r "operation:.*feature_flags_create" products/*/mcp/tools.yaml services/mcp/definitions/
   ```

5. **Check if enabled** — only generate scenarios for tools where `enabled: true`
   (or where `enabled` is not explicitly set to `false`).

## Using PR tests as a relevance and scenario signal

New or modified test files in the PR are a strong signal about what the developer
considers important to verify. Read them to:

1. **Discover affected code paths** — a test importing a serializer or calling
   a view function confirms that code is being exercised, even if the test file
   itself isn't in the MCP chain
2. **Surface edge cases** — parameterized tests, boundary value assertions,
   and error-case tests reveal conditions worth exercising through the MCP
3. **Understand intent** — test names and assertions describe the expected behavior,
   which helps write more targeted scenario prompts

### What to look for in tests

| Test pattern                        | What it reveals for scenario generation                                                                     |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Assertions on serializer validation | Which fields have constraints — generate scenarios that use valid values and verify the tool enforces them  |
| Multi-step test workflows           | Complex user journeys to model as end-to-end scenarios                                                      |
| Error/edge case tests               | Boundary conditions the scenario should exercise from the user perspective (but not replicate mechanically) |
| Permission/access tests             | Authorization behaviors to verify through the MCP tool surface                                              |
| Parameterized test variants         | Different configurations or input shapes worth covering                                                     |

### What NOT to do with tests

- Do not translate a unit test assertion into a scenario 1-to-1
  (e.g., "assert serializer rejects value X" → scenario that passes value X).
  Instead, generate a complementary scenario from the user's perspective.
- Do not skip scenario generation just because tests exist.
  Tests verify code correctness; scenarios verify the MCP tool experience.
- Do not generate scenarios for test utility changes (test helpers, fixtures,
  conftest) unless they reveal a behavioral change in the code under test.

## Edge cases

### Changes that look irrelevant but aren't

- **Migration files** — if they alter a model used by an MCP-backed serializer,
  the tool's response shape may change
- **Settings/config changes** — permission classes, throttle rates, or middleware
  changes can break tool authorization
- **Frontend-only changes** — not MCP-relevant unless they change
  generated API types that the MCP codegen also consumes

### Business logic deep in the call chain

If a change is in utility code or business logic (not a view/serializer/model),
trace callers upward:

```bash
grep -r "function_name" --include="*.py" -l | head -20
```

Follow the call chain until you reach a view or confirm it's not in the MCP path.
If the chain is more than 3 hops deep and you can't confirm, include it anyway —
false positives are cheaper than missed regressions.
