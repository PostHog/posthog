# MCP eval suite

End-to-end evals for the PostHog MCP server.
Each case sends a natural-language prompt to a Claude model that has been wired
up to a locally-running MCP worker (`wrangler dev`) which proxies to a real
PostHog backend, and measures: tool-call count, total latency, and (in later
PRs) final-answer correctness and tool-selection relevance.

## Architecture

```text
prompt → Anthropic SDK → MCP Python client → wrangler dev (services/mcp) → Django (PostHog)
```

The wrangler subprocess is started once per pytest session by
`harness.start_mcp_server` and torn down on exit.

## Running locally

You need three things running before invoking `pytest`:

1. **A local PostHog server**, reachable via HTTP (default `http://localhost:8010`).
   Use `./bin/start` or whatever your usual flow is.
2. **A personal API key** on that server with broad scopes (`*` is fine for evals).
   The MCP server passes this through as a Bearer token on every request.
3. **`pnpm install` inside `services/mcp`** so `pnpm wrangler dev` works.

Then:

```bash
export POSTHOG_MCP_EVAL_API_BASE_URL=http://localhost:8010   # default; can omit
export POSTHOG_MCP_EVAL_API_KEY=phx_...                      # required
export ANTHROPIC_API_KEY=sk-ant-...                          # required
# optional — to upload results to Braintrust
export BRAINTRUST_API_KEY=...

pytest ee/hogai/eval/mcp/eval_mcp_smoke.py -s
```

## Configuration knobs

| Env var                         | Default                 | Purpose                                   |
| ------------------------------- | ----------------------- | ----------------------------------------- |
| `POSTHOG_MCP_EVAL_API_BASE_URL` | `http://localhost:8010` | Where Django is running                   |
| `POSTHOG_MCP_EVAL_API_KEY`      | —                       | Personal API key on that PostHog instance |
| `POSTHOG_MCP_EVAL_MODEL`        | `claude-sonnet-4-5`     | Claude model to drive the tool-use loop   |
| `ANTHROPIC_API_KEY`             | —                       | LLM credentials                           |
| `BRAINTRUST_API_KEY`            | _unset_                 | Optional, enables Braintrust logging      |

## Files

- `harness.py` — boots `wrangler dev` on a free port, waits for it to be ready
- `mcp_runner.py` — Anthropic ↔ MCP tool-use loop, returns a `RunResult`
- `conftest.py` — session-scoped `mcp_server` fixture
- `eval_mcp_smoke.py` — single smoke case (more cases land in subsequent PRs)
- `../scorers/mcp.py` — `ToolCallCount`, `LatencyMs`

## Scope of this PR

This is the harness + a single smoke case. Subsequent PRs add:

- `AnswerCorrectness` LLM-judge scorer
- A broader dataset (~8 cases) covering insights, flags, errors, funnels
- A nightly CI workflow
