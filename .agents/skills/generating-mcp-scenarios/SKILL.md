---
name: generating-mcp-scenarios
description: 'Generate MCP integration test scenarios from PR diffs and execute them via Claude Code subprocesses. Use when reviewing a PR to determine if changes affect the MCP tool surface, generate natural-language test prompts that simulate real user workflows, execute them with MCP tools connected, and report results with end-to-end investigation on failure. Covers relevance detection, scenario generation, execution, failure investigation, and structured reporting.'
---

# Generating MCP integration scenarios

Generate natural-language test scenarios for the PostHog MCP server from PR diffs.
A scenario is a prompt that a Claude Code subprocess executes against live MCP tools,
simulating a real user workflow end-to-end.

## When to use this skill

- Reviewing a PR and you need to verify MCP tool workflows still work
- Asked to generate MCP test scenarios for a branch
- A pre-PR review suggests MCP-relevant changes
- Any code change touches the MCP hot path (generous interpretation)

## Workflow overview

### 1. Detect relevance

Analyze the diff to identify which MCP tools are affected.
Read the [relevance heuristics](./references/relevance-heuristics.md) for the full
file-pattern-to-tool mapping and tracing strategy.

The interpretation is **generous** — if a change is anywhere in the call chain
of an MCP tool (backend model, serializer, view, business logic), it's relevant.
When in doubt, include it.

### 2. Generate scenarios

Use **two inputs** to generate scenarios: the code diff and any tests in the PR.

#### Input: code diff

For each affected tool, write test prompts that simulate realistic user workflows.
Read the [scenario format](./references/scenario-format.md) for the YAML schema
and examples of well-written scenarios.

#### Input: tests in the PR

Read any new or modified test files in the diff — unit tests, integration tests,
E2E tests, API tests. These reveal what the developer considers important to verify
and expose edge cases, boundary conditions, and failure modes that the diff alone
might not make obvious.

Use the tests to **inform** scenario generation, not to replicate them:

- A unit test asserting that a serializer rejects negative values
  → generate a scenario where a user tries to create the entity with valid values
  and verify the response, not a scenario that passes negative values
- An integration test covering a multi-step workflow
  → generate a scenario that exercises the same workflow from a user perspective,
  using natural language instead of API calls
- An E2E test checking that deletion cascades correctly
  → generate a scenario where a user deletes the entity and then tries to
  retrieve related entities, verifying they're handled gracefully

The goal is **complementary coverage from a different angle**.
Tests verify code correctness; scenarios verify that the MCP tool surface
delivers a working experience for the same behaviors.
Overlap in what's covered is fine. Identical test logic rewritten as a prompt is not.

#### Key principles

- Scenarios are user-perspective prompts, not technical test cases
- Write them how a real person would talk to an agent
- Include verification steps (retrieve what you created, check the result)
- One scenario per file, organized by domain
- Cover the changed code path specifically, not just the tool in general

### 3. Persist scenarios

Save scenarios to `services/mcp/tests/scenarios/<domain>/`:

```text
services/mcp/tests/scenarios/
  product-analytics/
    create-trends-insight-with-breakdown.yaml
    query-funnel-conversion.yaml
  feature-flags/
    create-and-toggle-flag.yaml
  experiments/
    launch-experiment-with-holdout.yaml
```

Before creating a new scenario, check for existing ones covering the same workflow.
Update existing scenarios when the underlying behavior changes,
rather than creating duplicates.

### 4. Execute scenarios

**Scenarios must always run against the local dev MCP server, never production.**
The goal is to test the code on the current branch, not the deployed service.

#### Pre-flight: ensure the local environment is ready

1. **Verify the local MCP dev server is running** at `http://localhost:8787`.
   Start it with `hogli start` if it’s not already up.

   Quick smoke test:

   ```bash
   curl -s http://localhost:8787/mcp -o /dev/null -w "%{http_code}"
   ```

   Expect a 200 or 405 (method not allowed for GET is fine — it confirms
   the server is listening).

2. **Authenticate with the local dev PAT.**
   The local MCP server accepts Personal API Keys (`phx_` prefix) via
   a `Bearer` header — no OAuth browser flow needed.

   Run the management command to ensure the dev key exists:

   ```bash
   python manage.py setup_local_api_key
   ```

   This creates (or confirms) a deterministic PAT that works in local dev:
   `phx_dev_local_test_api_key_1234567890abcdef`

   The parent session’s MCP connection must include this key.
   If configuring via `.mcp.json` or `--mcp-config`:

   ```json
   {
     "mcpServers": {
       "posthog-local": {
         "url": "http://localhost:8787/mcp",
         "headers": {
           "Authorization": "Bearer phx_dev_local_test_api_key_1234567890abcdef"
         }
       }
     }
   }
   ```

   You can also pin the org and project to skip auto-detection:

   ```text
   http://localhost:8787/mcp?organization_id=<uuid>&project_id=<number>
   ```

   **Do not use project API keys (`phc_`)** — the MCP server rejects them.
   **Do not use OAuth (`pha_`)** — it requires a browser flow that can’t
   run unattended.

3. **Configure permissions for subagents.**
   Subagents spawned via the Agent tool inherit the parent session’s
   permission settings. Since subagents run without a human to approve
   prompts, the parent session must pre-approve the tools they need.

   Add these to your project `.claude/settings.local.json`:

   ```json
   {
     "permissions": {
       "allow": ["Bash(*)", "mcp__posthog-local__*"]
     }
   }
   ```

   Subagents need broad Bash access (test scenarios may use curl,
   python, or other commands) and MCP tool access to call PostHog
   tools against the local dev server.
   Use `settings.local.json` (not `settings.json`) so this permissive
   config stays local and doesn't get committed to the repo.

#### Tracing via PostHog LLM Analytics

Executor traces go to the **local dev** PostHog instance so you can
inspect the full agent session — every LLM call, tool use, token count,
and cost — in your local LLM observability UI.

Add the following to `.claude/settings.local.json`:

```json
{
  "env": {
    "POSTHOG_LLMA_CC_ENABLED": "true",
    "POSTHOG_API_KEY": "<local dev project API key (phc_...)>",
    "POSTHOG_HOST": "http://localhost:8000",
    "POSTHOG_LLMA_CUSTOM_PROPERTIES": "{\"ai_product\": \"mcp-scenario-test\"}"
  }
}
```

Find your project API key at http://localhost:8000 → Project settings.
`POSTHOG_HOST` must point at localhost.

Env vars from `settings.local.json` are loaded at session start.
Subagents spawned via the Agent tool inherit them automatically.

After execution, find traces in your local PostHog at
http://localhost:8000 → LLM observability, filtered by
`ai_product = mcp-scenario-test`.

#### Running executors

The agent runs the tests itself using the Agent tool to spawn subagents.
Each subagent receives the filled-in executor prompt and has access to
the MCP tools available in the current session.

Read the [executor prompt template](./references/executor-prompt-template.md)
for the full prompt structure fed to each subagent.

For each scenario, spawn a subagent via the Agent tool.
Instruct the subagent to write its full conversation log to a file
in `/tmp/mcp-scenarios/logs/` so the orchestrator (and the developer)
can review exactly what happened:

```javascript
Agent({
  description: '[MCP Test] <scenario-name>',
  prompt:
    '<filled-in executor prompt>\n\nWhen you are finished, write your full conversation log (every tool call, its response, your reasoning, and your final YAML report) to /tmp/mcp-scenarios/logs/<scenario-name>.log',
  run_in_background: true,
})
```

- Spawn independent scenarios in parallel (multiple Agent calls in one message)
- Subagents inherit the parent session’s MCP tools and env vars —
  no separate MCP config is needed
- Each subagent runs to completion and returns its YAML result report
- After all subagents complete, read the logs from
  `/tmp/mcp-scenarios/logs/` and aggregate the results

**Important:** Since subagents inherit the parent’s MCP configuration,
ensure the parent session is connected to the **local dev** MCP server,
not production. If the parent session’s MCP plugin points to production,
the subagents will too. Verify the parent’s MCP connection before
spawning executors.

### 5. Report results

After all subagents complete, aggregate their YAML reports into a
summary table. The table is the primary output the developer sees.

#### Summary table

Present results as a markdown table with these columns:

| Scenario                               | Status      | Comments                                                                           |
| -------------------------------------- | ----------- | ---------------------------------------------------------------------------------- |
| `create-trends-insight-with-breakdown` | ✅ Pass     | All tools called successfully, insight retrievable after creation                  |
| `query-funnel-conversion-by-referrer`  | ❌ Fail     | `funnel-query-run` returned 500 — breakdown_type rejects "event" after enum update |
| `flag-with-multivariate-rollout`       | ❌ Fail     | `flag-create` succeeded but multivariate config silently dropped (business logic)  |
| `search-and-retrieve-dashboard`        | ⚠️ Degraded | Response includes large filter blobs, making it slow and noisy                     |

- **✅ Pass**: one-line note on what was verified
- **❌ Fail**: include the error, the layer (mcp/api/business-logic), and the root cause
- **⚠️ Degraded**: describe the suboptimal behavior and suggested fix

After the table, add a brief summary line:
`**Result: X/Y passed, Z failed, W degraded**`

#### Detailed failure reports

Below the summary table, include a detailed section for each failure
or degraded result. Use the YAML format from the
[executor prompt template](./references/executor-prompt-template.md)
so the developer can see the full investigation (root cause, hypothesis,
evidence, repro steps).

#### Trace lookup

Each executor report includes a `session_id`. After presenting results,
use session IDs to look up traces in PostHog's LLM observability.
Use the `exploring-llm-traces` skill or query `posthog:llm-traces-list`
filtered by session to get the full tool call timeline, inputs, outputs,
and timing for each scenario run.

Read the [investigation protocol](./references/investigation-protocol.md)
for the full failure investigation and escalation workflow.
