# Agentic Tests Architecture

LLM-driven browser agents that continuously verify your product's key flows in production.

## How it works

An **AgenticTest** defines _what_ to test: a natural-language prompt, a target URL, optional assertions, and an optional cron schedule.
When executed, a cloud browser (Browserbase) opens the URL and a Claude agent follows the prompt — clicking, filling forms, navigating — then renders a pass/fail verdict.
Results are stored as **AgenticTestRun** records with full event logs, screenshots, and links to customer session replays.

### Execution flow

```text
AgenticTest
  ├── run_now / schedule trigger
  │     └── queue_agentic_test_runs()        # fan-out across configured regions
  │           └── execute_agentic_test_run()  # Celery worker
  │                 ├── run_agent()           # Playwright + Claude loop (runner.py)
  │                 │     ├── open Browserbase session (CDP)
  │                 │     ├── enumerate DOM → snapshot → Claude tool call → execute → repeat (max 20 steps)
  │                 │     └── yield AgentEvent stream (status, tool_call, tool_result, model_text, final)
  │                 ├── evaluate assertions (url_contains, event_captured via ClickHouse)
  │                 ├── link to customer's session replay (via _phag URL param + user-agent)
  │                 └── persist AgenticTestRun (status, output, log_entries)
  └── stream (SSE)
        └── same pipeline but bridges sync Playwright → async Django via queue, streams events to browser
```

### Flow auto-detection

Users can auto-detect key flows by pointing at a GitHub repo + domain.
This launches a sandboxed **Task** (from `products/tasks`) that:

1. Clones the repo in an isolated container
2. Reads code to understand user flows
3. Uses PostHog MCP tools to validate importance with analytics data
4. Calls `StructuredOutput` with proposed test flows

A `post_save` signal on `TaskRun` creates **AgenticTest** records in `proposed` status when structured output is saved.
The frontend detects the `StructuredOutput` tool call in the SSE stream and immediately transitions the banner to "done".

## Key files

### Backend

| File                                                  | What it does                                                                                                                        |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `backend/models/agentic_test/agentic_test.py`         | Test definition — prompt, target_url, schedule_cron, regions, assertions, status (active/paused/proposed/rejected)                  |
| `backend/models/agentic_test_run/agentic_test_run.py` | Execution record — log_entries, output, external_session_id, screenshot_url, assertion results                                      |
| `backend/logic/runner.py`                             | Python agent loop — Playwright + Claude (sonnet), 20-step max, ref-based DOM enumeration, tool set: goto/click/fill/press/wait/done |
| `backend/logic/browserbase.py`                        | Browserbase REST wrapper — session create/release, 4 regions                                                                        |
| `backend/logic/execution.py`                          | Orchestration — fan-out across regions, Celery dispatch, assertion evaluation, session replay linking                               |
| `backend/logic/detect_flows.py`                       | Flow detection — Pydantic output schema, `launch_detect_flows_task()`, `handle_detect_flows_completion()`                           |
| `backend/signals.py`                                  | `post_save` on TaskRun — fires `handle_detect_flows_completion` when output is written (deduped via in-memory set)                  |
| `backend/presentation/views.py`                       | DRF endpoints — CRUD, run_now, stream (SSE), activate/pause/reject, detect_flows (GET/POST/DELETE)                                  |
| `proposed_test_flows_prompt.md`                       | Prompt template for the flow-detection agent — includes sandbox constraints, prioritization philosophy, existing tests as XML       |

### Frontend

| File                                                          | What it does                                                                                                                    |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/scenes/AgenticTestsScene/AgenticTestsScene.tsx`     | List view — health summary, search + filter, table with row ribbons (amber for proposed, red for failing), empty state with CTA |
| `frontend/scenes/AgenticTestsScene/agenticTestsSceneLogic.ts` | Kea logic — test CRUD, filtering, sorting by status priority                                                                    |
| `frontend/scenes/AgenticTestScene/AgenticTestScene.tsx`       | Detail view — tabs for configuration (prompt, URL, schedule, regions, assertions), run history, live streaming                  |
| `frontend/scenes/AgenticTestsScene/detectFlowsLogic.ts`       | Flow detection state — form modal, SSE streaming to task run, step tracking, StructuredOutput completion detection              |
| `frontend/scenes/AgenticTestsScene/DetectFlowsBanner.tsx`     | Floating progress banner — 3 steps (setup → analyze → propose), latest activity preview, dismiss via soft-delete                |
| `frontend/scenes/AgenticTestsScene/DetectFlowsFormModal.tsx`  | Detection form — GitHub integration picker, repo selector, domain input                                                         |
| `frontend/scenes/AgenticTestsScene/DetectFlowsLogsModal.tsx`  | Agent logs viewer — autoscroll, edge-to-edge layout, direct log entry rendering                                                 |

## Models

```text
AgenticTest (team-scoped)
  ├── status: active | paused | proposed | rejected
  ├── prompt: natural-language instructions
  ├── target_url: where the browser agent starts
  ├── schedule_cron: optional 5-field UTC cron
  ├── regions: list of Browserbase regions
  ├── assertions: [{type: "url_contains", value: "/success"}, {type: "event_captured", event: "$purchase", within_seconds: 30}]
  └── has_many → AgenticTestRun
        ├── status: running | passed | failed | timeout | error
        ├── log_entries: [{type, data, step, timestamp}, ...]
        ├── output: {passed, reason, actions, usage, duration_seconds}
        ├── external_session_id: Browserbase session for replay deep-link
        └── posthog_session_id: customer's session replay ID
```

## Integration points

- **LLM Gateway**: `get_llm_client()` for Claude access (runner.py)
- **Browserbase**: Cloud browser sessions via REST API (browserbase.py)
- **Tasks product**: Flow detection runs as a sandboxed Task with `origin_product=AGENTIC_TESTS`
- **PostHog MCP**: Flow detection agent uses MCP tools to query analytics data
- **ClickHouse**: Assertion evaluation queries events table; session replay linking queries by URL param
- **Session Replays**: `_phag=run-<id>` URL param + custom user-agent enables automatic linking

## Configuration

| Setting                         | Purpose                                                          |
| ------------------------------- | ---------------------------------------------------------------- |
| `BROWSERBASE_API_KEY`           | Browserbase API authentication                                   |
| `BROWSERBASE_PROJECT_ID`        | Browserbase project scope                                        |
| `AGENTIC_TESTS_USE_MOCK_RUNNER` | Use deterministic mock instead of real browser (for development) |

## Development

```bash
# Run backend tests
hogli test products/agentic_tests/backend/tests/

# Start dev server (includes hot reload)
./bin/start

# Navigate to
# http://localhost:8010/agentic_tests
```

The mock runner (`AGENTIC_TESTS_USE_MOCK_RUNNER=true`) always passes — useful for testing the UI pipeline without Browserbase credentials.
