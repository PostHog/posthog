# Investigation protocol

When a scenario executor reports a failure or degraded result,
the orchestrator should understand the report and decide on next steps.
This document covers both the executor's investigation process
and the orchestrator's interpretation of results.

## Executor investigation (embedded in the executor prompt)

The executor follows a 5-step protocol when it encounters a problem.
This is already described in the executor prompt template.
The key steps are: record, classify, investigate, hypothesize, verify.

## Orchestrator interpretation

After collecting results from all executor subprocesses,
the orchestrator evaluates the aggregate.

### Reading a fail report

A fail report includes:

- **`layer`** — where in the stack the failure occurred:
  - `mcp`: the MCP server itself (schema, routing, tool registration).
    These are usually bugs in `services/mcp/` or `tools.yaml` config.
  - `api`: the Django REST API returned an error.
    These are usually serializer validation issues, permission problems,
    or view-level bugs.
  - `business-logic`: the API succeeded but returned wrong data.
    These are usually model-level or service-layer bugs.
  - `infrastructure`: the executor timed out, crashed, or couldn't connect.
    Retry before investigating further.

- **`root_cause`** — the executor's assessment of what broke.
  Cross-reference with the PR diff: does the changed code touch this area?

- **`hypothesis` + `prediction`** — the executor's theory about why and what would fix it.
  The orchestrator should evaluate whether the hypothesis is consistent with the diff.

- **`evidence`** — supporting observations. Check these are factual, not assumed.

- **`repro_steps`** — how to reproduce. Use these to write regression scenarios
  or to guide the developer to the fix.

### Reading a degraded report

A degraded report means the workflow succeeded but the experience is suboptimal.
Common categories:

- **Missing response fields** — the tool returns data but omits fields
  the user would need. Usually a `response.include`/`response.exclude`
  issue in `tools.yaml`.
- **Confusing error messages** — the tool fails with a generic error
  instead of a helpful message. Usually a serializer `error_messages`
  or `help_text` issue.
- **Extra round-trips** — the user has to call multiple tools
  to accomplish what should be one step. May indicate a missing tool
  or a tool that should return more data.
- **Schema confusion** — the tool's parameter names or descriptions
  are unclear, causing the executor to guess or call `info` first.
  Usually a `param_overrides.description` issue in `tools.yaml`.

### Inspecting traces

Every executor report includes a `session_id`. Use it to inspect the full
tool call timeline in PostHog's LLM observability:

1. **Via MCP tool** — call `posthog:llm-traces-list` filtered by the session ID
   to get the trace, then `posthog:llm-trace` to inspect individual spans
2. **Via the `exploring-llm-traces` skill** — load it and pass the session ID
   for a guided walkthrough of the trace
3. **Via the PostHog UI** — navigate to LLM observability → traces and
   search by the session ID

Traces show the exact tool call sequence, inputs, outputs, and timing.
This is especially useful for:

- Verifying the executor actually called the tools it claims
- Seeing the exact payloads sent and received (not just the executor's summary)
- Spotting latency issues that the executor might not flag as degraded
- Debugging intermittent failures where the executor's evidence is incomplete

For failed scenarios, always inspect the trace before escalating.
The executor's hypothesis may be wrong, but the trace data is ground truth.

### Aggregating results

When reporting to the developer:

1. **Lead with failures** — these are the actionable items
2. **Group by layer** — "2 API failures, 1 MCP failure" is more useful
   than a flat list
3. **Connect to the diff** — for each failure, note which changed file
   is likely responsible
4. **Include trace links** — for each failure, include the session ID
   so the developer can inspect the trace directly
5. **Include degraded items as suggestions** — these aren't blockers
   but improve the experience
6. **Summarize passes briefly** — "12/15 scenarios passed" is sufficient

### Example aggregate report

```markdown
## MCP scenario results: 12/15 passed

### Failures (3)

**API layer (2):**

- `create-trends-insight-with-breakdown` — insight-create returns 400
  when filters are omitted. The param_overrides in tools.yaml marks
  filters as optional but InsightSerializer requires it.
  Likely caused by: changes to `products/product_analytics/mcp/tools.yaml`
  Trace: session `mcp-test-create-trends-1749830400`

- `query-funnel-conversion-by-referrer` — funnel-query-run returns 500.
  The breakdown_type field rejects "event" as a value since the enum
  was updated. Likely caused by: changes to `posthog/api/insight.py`
  Trace: session `mcp-test-query-funnel-1749830400`

**Business logic (1):**

- `flag-with-multivariate-rollout` — flag-create succeeds but the
  multivariate config is silently dropped. The serializer accepts
  the field but the model ignores it during save.
  Likely caused by: changes to `products/feature_flags/backend/models.py`
  Trace: session `mcp-test-flag-multivariate-1749830400`

### Degraded (1)

- `search-and-retrieve-dashboard` — dashboard-list returns all fields
  including large filter blobs, making responses slow and noisy.
  Suggestion: add response.exclude for heavy fields.
  Trace: session `mcp-test-search-dashboard-1749830400`

### Passed (11)

All other scenarios completed successfully.
```

## When to escalate vs. fix

- **MCP layer failures from direct changes** — the PR author should fix these
  before merge. They're usually typos or config mistakes in tools.yaml.
- **API layer failures from indirect changes** — flag for review.
  The author may not realize their serializer change affects an MCP tool.
- **Business logic failures** — these may be intentional behavior changes.
  Ask the author whether the old behavior was correct.
- **Infrastructure failures** — retry first. If persistent, it's an environment issue,
  not a code issue.
- **Degraded results** — these are improvement suggestions, not blockers.
  Include them in the report but don't block the PR.
