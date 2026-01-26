# Batch Trace Summarization

Hourly Temporal workflow that generates summaries and embeddings of LLM traces for clustering and semantic search.

## How It Works

1. Coordinator workflow runs hourly, spawning child workflows for each team in `ALLOWED_TEAM_IDS`
2. Per-team workflow queries recent traces (default: last 60 min, max 100 traces)
3. For each trace: fetch data → generate text repr → call LLM → emit `$ai_trace_summary` event → queue embedding via Kafka
4. Embeddings processed asynchronously by Rust worker, stored in `document_embeddings` table

The workflow is **idempotent** - rerunning on the same window regenerates the same results. Uses `temporalio.workflow.now()` for deterministic timestamps.

## File Structure

```text
workflow.py           # Per-team workflow (llma-trace-summarization)
coordinator.py        # Multi-team coordinator (llma-trace-summarization-coordinator)
schedule.py           # Hourly schedule configuration
models.py             # Data models (inputs, results, metrics)
constants.py          # Timeouts, defaults, retry policies
sampling.py           # Query traces from time window
summarization.py      # Generate summary, emit event, queue embedding
tests/
  test_workflow.py    # Workflow and activity tests
  test_coordinator.py # Coordinator workflow tests
```

## Workflows

### Coordinator: `llma-trace-summarization-coordinator`

Spawns child workflows for teams in `ALLOWED_TEAM_IDS` (configured in `constants.py`).

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

### Team Allowlist

Edit `ALLOWED_TEAM_IDS` in `constants.py`. Empty list = coordinator skips all teams. Manual triggers can target any team.

## Configuration

Key constants in `constants.py`:

| Constant                             | Default        | Description                 |
| ------------------------------------ | -------------- | --------------------------- |
| `DEFAULT_MAX_ITEMS_PER_WINDOW`       | 10             | Max items per window        |
| `DEFAULT_BATCH_SIZE`                 | 3              | Concurrent trace processing |
| `DEFAULT_MODE`                       | "detailed"     | Summary detail level        |
| `DEFAULT_MODEL`                      | "gpt-4.1-nano" | LLM model for summarization |
| `DEFAULT_WINDOW_MINUTES`             | 60             | Time window to query        |
| `WORKFLOW_EXECUTION_TIMEOUT_MINUTES` | 120            | Max workflow duration       |
| `SAMPLE_TIMEOUT_SECONDS`             | 300            | Sampling activity timeout   |
| `GENERATE_SUMMARY_TIMEOUT_SECONDS`   | 300            | Summary activity timeout    |

Retry policies: `SAMPLE_RETRY_POLICY` (3 attempts), `SUMMARIZE_RETRY_POLICY` (2 attempts), `COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY` (2 attempts).

## Error Handling

- Individual trace failures are logged but don't fail the workflow
- Embedding failures tracked separately, don't fail summary generation
- Activity retries use exponential backoff via centralized retry policies

## Testing

```bash
pytest posthog/temporal/llm_analytics/trace_summarization/ -v
```
