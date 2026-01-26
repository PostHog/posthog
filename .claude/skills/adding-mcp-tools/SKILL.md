---
name: adding-mcp-tools
description: Guidelines to add a new tool to the PostHog MCP (Model Context Protocol) server. MCP tools wrap backend Python tools and expose them via the TypeScript MCP service.
---

# Adding MCP Tools

Use the steps below to add a new tool to the MCP server. MCP tools in PostHog wrap Python backend tools (`ee/hogai/tools/`) and expose them via a TypeScript MCP service (`services/mcp/typescript/`).

## Overview

Adding a new MCP tool requires changes to these files:

1. **Python backend** - `ee/api/max_tools.py` (register the tool)
2. **TypeScript schema** - `services/mcp/typescript/src/schema/max-tools.ts` (Zod schema)
3. **TypeScript tool** - `services/mcp/typescript/src/tools/max-tools/<toolName>.ts` (handler)
4. **TypeScript index** - `services/mcp/typescript/src/tools/max-tools/index.ts` (registration)
5. **Tool definitions** - `services/mcp/schema/tool-definitions.json` (metadata)

## Naming conventions

- **Python tool name**: `snake_case` (e.g., `create_insight`)
- **TypeScript file name**: `camelCase.ts` (e.g., `createInsight.ts`)
- **MCP tool name**: `phai-kebab-case` (e.g., `phai-create-insight`)
- **Schema export**: `Max<PascalCase>ToolArgsSchema` (e.g., `MaxCreateInsightToolArgsSchema`)

## Critical: Schema and description parity

**The MCP tool schema and description MUST match the Python MaxTool exactly.** The MCP TypeScript layer is a thin wrapper - all validation and execution happens in Python. Any mismatch will cause:

- Validation errors if required fields differ
- Silent bugs if field types don't match
- Confusing LLM behavior if descriptions diverge

Always reference the Python tool's `args_schema` (Pydantic model) and `description` when creating the MCP wrapper.

## Step 1: Verify the Python backend tool exists

Before creating the MCP wrapper, ensure the Python tool exists in `ee/hogai/tools/` and is properly exported. The tool must:

- Inherit from `MaxTool`
- Define an `args_schema` (Pydantic BaseModel)
- Implement `_arun_impl()` returning `(content: str, artifact: Optional[Any])`

**Important**: Read the Python tool's `args_schema` carefully. Your Zod schema must mirror it exactly:

- Same field names
- Same types (string/number/boolean/enum/object)
- Same required vs optional fields
- Same default values

## Step 2: Register Python tool in max_tools.py

Add the tool to the `MAX_TOOLS` dict in `ee/api/max_tools.py`:

```python
from ee.hogai.tools import MyNewTool  # Add import

MAX_TOOLS: dict[str, type[MaxTool]] = {
    # ... existing tools
    "my_new_tool": MyNewTool,  # Add entry (snake_case key)
}
```

This automatically creates the API endpoint at `POST /api/environments/{projectId}/max_tools/my_new_tool/`.

## Step 3: Define the Zod schema

Add the schema to `services/mcp/typescript/src/schema/max-tools.ts`. **Copy the structure directly from the Python Pydantic model.**

Example Python Pydantic schema:

```python
class MyNewToolArgs(BaseModel):
    param1: str = Field(description="Description of param1")
    param2: int | None = Field(default=None, description="Optional param2")
```

Corresponding Zod schema (must match exactly):

```typescript
export const MaxMyNewToolArgsSchema = z.object({
  param1: z.string().describe('Description of param1'), // Copy description from Python
  param2: z.number().nullable().optional().describe('Optional param2'),
})

export type MaxMyNewToolArgs = z.infer<typeof MaxMyNewToolArgsSchema>
```

### Type mapping (Python → Zod)

| Python type                | Zod equivalent              |
| -------------------------- | --------------------------- |
| `str`                      | `z.string()`                |
| `int`                      | `z.number()`                |
| `float`                    | `z.number()`                |
| `bool`                     | `z.boolean()`               |
| `list[T]`                  | `z.array(...)`              |
| `dict[str, T]`             | `z.record(z.string(), ...)` |
| `T \| None`                | `z.....nullable()`          |
| `Optional[T]` with default | `z.....optional()`          |
| `Literal["a", "b"]`        | `z.enum(["a", "b"])`        |
| Nested `BaseModel`         | Nested `z.object({...})`    |

### Important schema guidelines

- **Copy descriptions verbatim** from Python Field descriptions
- Match required vs optional fields exactly
- Use discriminated unions for conditional schemas (match Python's approach)
- Reuse shared schemas when possible (see `RecordingFilterGroupSchema`)

## Step 4: Create the TypeScript tool handler

Create `services/mcp/typescript/src/tools/max-tools/myNewTool.ts`:

```typescript
import type { z } from 'zod'

import { MaxMyNewToolArgsSchema } from '@/schema/max-tools'
import type { Context, ToolBase } from '@/tools/types'

const schema = MaxMyNewToolArgsSchema
type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
  const projectId = await context.stateManager.getProjectId()
  const result = await context.api.maxTools({ projectId }).invoke({
    toolName: 'my_new_tool', // Must match Python snake_case name
    args: params,
  })
  if (!result.success) {
    throw new Error(`phai-my-new-tool failed: ${result.error.message}`)
  }
  return { content: result.data.content, artifact: result.data.artifact }
}

const tool = (): ToolBase<typeof schema> => ({
  name: 'phai-my-new-tool', // kebab-case with phai- prefix
  schema,
  handler,
})

export default tool
```

## Step 5: Register in the tools index

Add to `services/mcp/typescript/src/tools/max-tools/index.ts`:

```typescript
import myNewTool from './myNewTool'

export const PHAI_TOOLS_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
  // ... existing tools
  'phai-my-new-tool': myNewTool, // Add entry
}
```

## Step 6: Add tool definition metadata

Add an entry to `services/mcp/schema/tool-definitions.json`. **The `description` field should match the Python tool's `description` class attribute.**

```json
{
  "phai-my-new-tool": {
    "description": "Copy from Python tool's description attribute. This is shown to the LLM and must match to ensure consistent behavior.",
    "category": "PostHog AI",
    "feature": "phai-tools",
    "summary": "Short one-line summary for UI display",
    "title": "My New Tool",
    "required_scopes": ["query:read"],
    "annotations": {
      "destructiveHint": false,
      "idempotentHint": false,
      "openWorldHint": true,
      "readOnlyHint": true
    }
  }
}
```

**Note**: The `description` here is what the LLM sees when deciding which tool to use. If it differs from the Python tool's description, you may get inconsistent behavior between MCP clients and the in-app Max assistant.

### Annotations explained

- `destructiveHint`: Tool can delete or modify existing data
- `idempotentHint`: Same input always produces same output
- `openWorldHint`: Tool interacts with external systems or data
- `readOnlyHint`: Tool only reads data, no side effects

### Required scopes

Common scopes:

- `query:read` - Execute queries
- `insight:read` / `insight:write` - Read/create insights
- `dashboard:read` / `dashboard:write` - Read/create dashboards
- `session_recording:read` - Access session recordings

## Testing

1. **Python backend**: Add tests in `ee/hogai/tools/test/test_<tool_name>.py`
2. **API endpoint**: Test via curl or the API client
3. **MCP integration**: Test via the MCP server with an MCP client

Example curl test:

```bash
curl -X POST "http://localhost:8000/api/environments/<project_id>/max_tools/my_new_tool/" \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"param1": "value1"}'
```

## Example: Complete flow

For a tool named `analyze_funnel`:

| Component           | Value                                                   |
| ------------------- | ------------------------------------------------------- |
| Python tool class   | `AnalyzeFunnelTool`                                     |
| Python registry key | `"analyze_funnel"`                                      |
| TypeScript file     | `analyzeFunnel.ts`                                      |
| MCP tool name       | `"phai-analyze-funnel"`                                 |
| Schema export       | `MaxAnalyzeFunnelToolArgsSchema`                        |
| API endpoint        | `POST /api/environments/{id}/max_tools/analyze_funnel/` |
