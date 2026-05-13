# Executor prompt template

This is the prompt template sent to a subagent (via the Agent tool)
that executes a scenario against the **local dev** MCP server.

The orchestrator fills in the template variables and passes the result
as the `prompt` parameter to the Agent tool.

Subagents inherit the parent session's MCP configuration.
**The parent session must be connected to the local dev MCP server,
not production.** Verify this before spawning executors.

## Template

````text
You are executing an MCP integration test scenario against the LOCAL PostHog MCP
dev server. You are connected to the local dev server at localhost:8787, not production.
Your job is to simulate a real user workflow and determine whether it works correctly.

Your MCP session ID is: {{session_id}}
All your tool calls are being traced under this session ID in PostHog's
LLM observability. Include it in your final report so the developer can
inspect the full trace.

## Scenario: {{name}}

{{prompt}}

## Expected tools

These tools are expected to be involved, but you may call others
for discovery or verification:

{{tools_in_scope as bullet list}}

## Success criteria

{{success_criteria as bullet list}}

## Execution instructions

1. Work through the scenario naturally, as a user would.
   Start by discovering available tools if you're unsure which to call.
2. After each tool call, check the response:
   - Did it succeed (no error)?
   - Does the data make sense for what was requested?
   - Are there missing fields, unexpected nulls, or truncated results?
3. After completing the workflow, verify the success criteria.
   Call additional tools to confirm side effects (e.g., retrieve what you created).
4. If everything passes, report success.
5. If anything fails or behaves unexpectedly, investigate before reporting.

## Investigation protocol (on failure or unexpected behavior)

If a tool call fails or produces unexpected results, do not report immediately.
Investigate first:

### Step 1: Record
Capture the exact error message, HTTP status code (if visible),
and the full tool response.

### Step 2: Classify the failure layer
- **MCP layer**: schema validation error before the API call,
  tool not found, parameter type mismatch
- **API layer**: HTTP 4xx/5xx from the Django backend,
  serializer validation error, permission denied
- **Business logic**: tool succeeded (2xx) but returned wrong data,
  missing fields, or incorrect state

### Step 3: Investigate
- Call related tools to check state
  (e.g., list entities to see if creation partially succeeded)
- Try the same call with slightly different parameters
  to isolate which input triggers the error
- Check if the tool's schema matches what the error expects
  (schema mismatch between MCP tool definition and Django serializer)
- Use execute-sql or query tools to inspect the underlying data if available

### Step 4: Form a hypothesis
State a specific hypothesis in this format:
- "I believe [root cause] is happening because [evidence]"
- "I predict that [fix] would resolve this because [reasoning]"

### Step 5: Test the hypothesis
Make one additional tool call to verify or falsify your hypothesis.
For example, if you think a required field is missing from the schema,
check the tool's schema definition.

## Output format

When done, output your report as a YAML block.
This is the ONLY output format the orchestrator will parse.

For a passing scenario:

```yaml
status: pass
scenario: {{name}}
session_id: {{session_id}}
tools_called:
  - tool-name-1
  - tool-name-2
notes: "optional — anything worth noting even on success"
```

For a failing scenario:

```yaml
status: fail
scenario: {{name}}
session_id: {{session_id}}
tools_called:
  - tool-name-1
  - tool-name-2
error: "exact error message or unexpected behavior description"
investigation:
  layer: mcp | api | business-logic
  root_cause: "what specifically went wrong"
  hypothesis: "why it went wrong — the underlying cause"
  prediction: "what change would fix it"
  evidence:
    - "observation 1 supporting the hypothesis"
    - "observation 2 supporting the hypothesis"
repro_steps:
  - "step 1 to reproduce"
  - "step 2 to reproduce"
```

For a degraded scenario (works but suboptimal):

```yaml
status: degraded
scenario: {{name}}
session_id: {{session_id}}
tools_called:
  - tool-name-1
  - tool-name-2
issue: "what's suboptimal about the experience"
severity: low | medium | high
impact: "user-facing consequence"
suggestion: "what would improve it"
```

## Conversation log

After producing your YAML report, write your full conversation log
to `/tmp/mcp-scenarios/logs/{{name}}.log`. The log should include:

- Every tool call you made (tool name and input)
- Every tool response (full output or a summary if very large)
- Your reasoning between tool calls
- Your final YAML report

This file is the ground truth for what happened during execution.
The orchestrator and developer will use it to review your work,
debug failures, and verify your investigation.
````

## Template variables

| Variable               | Source                                                            |
| ---------------------- | ----------------------------------------------------------------- |
| `{{name}}`             | `name` field from the scenario YAML                               |
| `{{session_id}}`       | Generated by the orchestrator: `mcp-test-<name>-<unix-timestamp>` |
| `{{prompt}}`           | `prompt` field from the scenario YAML                             |
| `{{tools_in_scope}}`   | `tools_in_scope` field, formatted as a markdown bullet list       |
| `{{success_criteria}}` | `success_criteria` field, formatted as a markdown bullet list     |

## Notes for the orchestrator

- **Verify the parent session's MCP connection points to local dev
  before spawning subagents.** Subagents inherit the parent's MCP
  configuration. If the parent is connected to production, so are
  the subagents.
- **Use the Agent tool** to spawn executor subagents. Pass the
  filled-in template as the `prompt` parameter. Use
  `run_in_background: true` for parallel execution.
- Spawn independent scenarios in parallel by including multiple
  Agent tool calls in a single message.
- The executor subagent has no context about the PR or the diff.
  It only knows the scenario prompt and success criteria.
  This is intentional — it tests the tool from a user's perspective.
- Parse the YAML block from the subagent's returned result.
  Look for a fenced code block tagged `yaml` containing a `status:` field.
- If a subagent times out or crashes without producing a report,
  treat it as a fail with `layer: infrastructure`.
