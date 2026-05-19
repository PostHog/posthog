# Batch Trace Summarization

Hourly Temporal workflow that generates summaries and embeddings of LLM traces for clustering and semantic search.

## How It Works

1. Coordinator workflow runs hourly, discovering teams dynamically (guaranteed teams + sampled teams with AI events)
2. Per-team workflow queries recent traces (default: last 60 min, max 15 items)
3. For each item (trace or generation), a two-step activity pipeline runs:
   - **fetch_and_format**: fetch data from ClickHouse → format text repr → store in Redis (gzip-compressed)
   - **summarize_and_save**: read text repr from Redis → call LLM → emit summary event → queue embedding → clean up Redis key
4. Embeddings processed asynchronously by Rust worker, stored in `document_embeddings` table

The two-step split means the expensive LLM call is never re-executed if save/embed fails, and heartbeats work on the I/O-bound summarize step (the CPU-bound formatting is isolated in its own shorter activity).

The workflow is **idempotent** - rerunning on the same window regenerates the same results. Uses `temporalio.workflow.now()` for deterministic timestamps.

## File Structure

```text
workflow.py             # Per-team workflow (llma-trace-summarization)
coordinator.py          # Multi-team coordinator (llma-trace-summarization-coordinator)
schedule.py             # Hourly schedule configuration
models.py               # Data models (inputs, results, metrics, inter-activity contracts)
constants.py            # Timeouts, defaults, retry policies
sampling.py             # Query traces from time window
fetch_and_format.py     # Activity 1: fetch + format + store text_repr in Redis
summarize_and_save.py   # Activity 2: read Redis + LLM call + save event + embed
state.py                # Redis intermediate storage helpers (gzip compress/decompress)
queries.py              # ClickHouse queries for trace fetching
utils.py                # Datetime formatting utilities
tests/
  test_workflow.py      # Workflow, sampling, and parse_inputs tests
  test_fetch_and_format.py  # Fetch and format activity tests
  test_summarize_and_save.py # Summarize and save activity tests
  test_state.py         # Redis storage helper tests
  test_coordinator.py   # Coordinator workflow tests
```

## Activity Pipeline

```text
Per item (trace or generation):

  fetch_and_format_activity (2 min timeout, 60s heartbeat)
    └─ fetch from ClickHouse → format text_repr → gzip + store in Redis
    └─ returns: redis_key, event_count, text_repr_length

  summarize_and_save_activity (15 min timeout, 60s heartbeat)
    └─ read text_repr from Redis → LLM call → save event → embed → delete Redis key
    └─ returns: SummarizationActivityResult
```

Both activities are unified — they handle trace-level and generation-level summarization by branching on `generation_id` presence.

## Workflows

### Coordinator: `llma-trace-summarization-coordinator`

Discovers teams dynamically via `get_team_ids_for_llm_analytics` (guaranteed teams + a random sample of teams with AI events, configured in `team_discovery.py`).

**Inputs** (`BatchTraceSummarizationCoordinatorInputs`): `max_traces`, `batch_size`, `mode`, `window_minutes`, `model` - all optional with sensible defaults.

**Returns** `CoordinatorResult`: `teams_processed`, `teams_failed`, `failed_team_ids`, `total_items`, `total_summaries`

### Per-Team: `llma-trace-summarization`

**Inputs** (`BatchSummarizationInputs`):

- `team_id` (required)
- `max_traces` (default: 100), `batch_size` (default: 5), `mode` (default: "detailed"), `window_minutes` (default: 60)
- `window_start`, `window_end` - optional explicit window (RFC3339)
- `model` - optional LLM model override

**Returns** `BatchSummarizationResult`: `batch_run_id`, `metrics` (items_queried, summaries_generated/skipped/failed, embedding_requests_succeeded/failed, duration_seconds)

## Output Events

Each trace gets a `$ai_trace_summary` event:

```python
{
    "$ai_trace_id": "original_trace_id",
    "$ai_batch_run_id": "team_123_2025-01-15T12:00:00Z",
    "$ai_summary_mode": "detailed",
    "$ai_summary_title": "User authentication flow",
    "$ai_summary_flow_diagram": "graph TD; A-->B;",
    "$ai_summary_bullets": [{"text": "...", "line_refs": "L1-5"}],
    "$ai_summary_interesting_notes": [{"text": "...", "line_refs": "L10"}],
    "$ai_text_repr_length": 1234,
    "$ai_event_count": 5,
    "trace_timestamp": "2025-01-15T12:00:00Z"
}
```

Each generation gets a `$ai_generation_summary` event with `$ai_generation_id` and `$ai_trace_id`.

## Usage

### Manual Trigger (Temporal CLI)

```bash
# Per-team workflow
temporal workflow start \
  --type llma-trace-summarization \
  --task-queue development-task-queue \
  --workflow-id "batch-summarization-team-1-$(date +%Y%m%d%H%M%S)" \
  --input '{"team_id": 1}'

# With custom parameters
temporal workflow start \
  --type llma-trace-summarization \
  --task-queue development-task-queue \
  --workflow-id "batch-summarization-team-1-$(date +%Y%m%d%H%M%S)" \
  --input '{"team_id": 1, "max_traces": 50, "window_minutes": 30}'

# Coordinator (all teams in allowlist)
temporal workflow start \
  --type llma-trace-summarization-coordinator \
  --task-queue development-task-queue \
  --workflow-id "batch-summarization-coordinator-$(date +%Y%m%d%H%M%S)" \
  --input '{}'
```

> Local dev uses `development-task-queue`, production uses `general-purpose-task-queue`.

### Scheduled Execution

The coordinator runs hourly via Temporal schedule (configured in `schedule.py`). Verify at http://localhost:8233 → schedule: `llma-trace-summarization-coordinator-schedule`.

### Team Discovery

Teams are discovered dynamically via `team_discovery.py`. Guaranteed teams (in `GUARANTEED_TEAM_IDS`) are always included, plus a configurable random sample of teams with AI events. Manual triggers can target any team.

## Configuration

Key constants in `constants.py`:

| Constant                                    | Default        | Description                                     |
| ------------------------------------------- | -------------- | ----------------------------------------------- |
| `DEFAULT_MAX_ITEMS_PER_WINDOW`              | 15             | Max items per window                            |
| `DEFAULT_BATCH_SIZE`                        | 5              | Concurrent item processing                      |
| `DEFAULT_MAX_CONCURRENT_TEAMS`              | 5              | Max teams to process in parallel                |
| `DEFAULT_MODE`                              | "detailed"     | Summary detail level                            |
| `DEFAULT_MODEL`                             | "gpt-4.1-nano" | LLM model for summarization                     |
| `DEFAULT_WINDOW_MINUTES`                    | 60             | Time window to query                            |
| `WORKFLOW_EXECUTION_TIMEOUT_MINUTES`        | 30             | Max per-team workflow duration                  |
| `COORDINATOR_EXECUTION_TIMEOUT_MINUTES`     | 55             | Max coordinator workflow duration               |
| `SAMPLE_TIMEOUT_SECONDS`                    | 900            | Sampling activity timeout (per attempt)         |
| `FETCH_AND_FORMAT_START_TO_CLOSE_TIMEOUT`   | 120s           | Fetch + format activity timeout (per attempt)   |
| `FETCH_AND_FORMAT_HEARTBEAT_TIMEOUT`        | 60s            | Heartbeat window for fetch activity             |
| `SUMMARIZE_AND_SAVE_START_TO_CLOSE_TIMEOUT` | 900s           | Summarize + save activity timeout (per attempt) |
| `SUMMARIZE_AND_SAVE_HEARTBEAT_TIMEOUT`      | 60s            | Heartbeat window for summarize activity         |

Retry policies: `SAMPLE_RETRY_POLICY` (3 attempts), `FETCH_AND_FORMAT_RETRY_POLICY` (3 attempts), `SUMMARIZE_AND_SAVE_RETRY_POLICY` (4 attempts with backoff, `TextReprExpiredError` non-retryable), `COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY` (2 attempts). All retry policies exclude `ValueError` and `TypeError` from retries.

## Redis Intermediate Storage

Text representations (up to 2 MB) are stored in Redis between the two activities to keep Temporal workflow history small (~100 bytes per reference). Key pattern: `llma:summarization:{trace|generation}:{team_id}:{item_id}:text_repr`. Keys have a 200-minute TTL (exceeds the 30-minute workflow timeout) and are cleaned up after use. See `state.py`.

## Error Handling

- Individual item failures are logged but don't fail the workflow
- `TextReprExpiredError` is non-retryable (Redis key missing means fetch must re-run, but this is handled by workflow-level retry)
- Embedding failures tracked separately, don't fail summary generation
- Activity retries use exponential backoff via centralized retry policies

## Testing

```bash
pytest posthog/temporal/llm_analytics/trace_summarization/tests/ -v
```
