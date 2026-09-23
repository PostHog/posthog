---
name: debugging-signals-pipeline
description: >
  Debug the signals pipeline locally end-to-end. Covers emitting test signals
  from fixtures, monitoring Temporal workflows via the REST API, reading sandbox
  agent logs from object storage, inspecting Docker sandbox containers, and
  diagnosing common failures (stale ClickHouse embeddings, agentsh network
  denials, inactivity timeouts). Use when a signal isn't reaching the inbox,
  a signal-report-summary workflow fails, or a sandbox task run times out.
---

# Debugging the signals pipeline

## Pipeline flow

```text
emit_signals_from_fixture
  → signal-emitter (Temporal workflow)
    → buffer-signals (batches signals, 5s flush timer)
      → safety_filter_activity
      → flush_signals_to_s3_activity
      → signal_with_start_grouping_v2_activity
        → team-signal-grouping-v2 (30s batch collect window)
          → read_signals_from_s3_activity
          → get_embedding_activity + generate_search_queries_activity
          → run_signal_semantic_search_activity
          → match_signal_to_report_activity
          → assign_and_emit_signal_activity
          → wait_for_signal_in_clickhouse_activity
          → (if new report) signal-report-summary
            → fetch_signals_for_report_activity
            → report_safety_judge_activity
            → select_repository_activity (spawns Docker sandbox)
```

## Emitting test signals

```bash
# Emit a single signal from the Zendesk fixture at offset 26
DEBUG=1 python manage.py emit_signals_from_fixture --type zendesk --team-id 1 --offset 26 --limit 1

# Clean up all signal data before re-emitting (avoids stale matches)
DEBUG=1 python manage.py cleanup_signals --team-id 1 --yes

# Check pipeline status
python manage.py signal_pipeline_status --team-id 1 --wait --expected-signals 1 --poll-interval 10
```

Always clean up before re-emitting to avoid stale embeddings causing phantom report matches.

## Monitoring Temporal workflows

The Temporal UI runs at `http://localhost:8081`. The REST API is useful for scripted inspection.

### List recent workflows

```bash
curl -s 'http://localhost:8081/api/v1/namespaces/default/workflows?query=ORDER+BY+StartTime+DESC&maximumPageSize=15' \
  | python3 -c "
import sys, json
for wf in json.load(sys.stdin).get('executions', []):
    info = wf['execution']
    status = wf['status'].replace('WORKFLOW_EXECUTION_STATUS_', '')
    print(f'{wf[\"startTime\"][:19]}  {status:20s} {wf[\"type\"][\"name\"]:35s} {info[\"workflowId\"][:90]}')
"
```

### Inspect workflow history

```bash
WF_ID="buffer-signals-1"  # or team-signal-grouping-v2-1, signals-report:1:<uuid>
curl -s "http://localhost:8081/api/v1/namespaces/default/workflows/$WF_ID/history?maximumPageSize=200" \
  | python3 -c "
import sys, json
for event in json.load(sys.stdin).get('history', {}).get('events', []):
    etype = event['eventType'].replace('EVENT_TYPE_', '')
    etime = event['eventTime'][:19]
    details = ''
    for key, attrs in event.items():
        if key.endswith('Attributes') and isinstance(attrs, dict):
            if 'activityType' in attrs: details = attrs['activityType'].get('name', '')
            elif 'signalName' in attrs: details = f'signal: {attrs[\"signalName\"]}'
            elif 'startToFireTimeout' in attrs: details = f'timer: {attrs[\"startToFireTimeout\"]}'
            elif 'failure' in attrs: details = f'FAILED: {attrs[\"failure\"].get(\"message\", \"\")[:200]}'
    if details: print(f'  {etime}  {etype:50s} {details}')
"
```

### Inspect a previous run (continued-as-new)

When a workflow has continued-as-new, use the `execution.runId` query param:

```bash
curl -s "http://localhost:8081/api/v1/namespaces/default/workflows/$WF_ID/history?execution.runId=<run-id>&maximumPageSize=200"
```

## Reading sandbox agent logs

Agent logs are stored in object storage (MinIO locally) as JSONL files.
The log URL is on the `TaskRun` model.

```python
# In Django shell (python manage.py shell)
from products.tasks.backend.models import TaskRun
from posthog.storage import object_storage

# Find the most recent task run
run = TaskRun.objects.order_by("-created_at").first()
print(f"status: {run.status}, error: {run.error_message}")
print(f"log_url: {run.log_url}")

# Read the log
content = object_storage.read(run.log_url, missing_ok=True)

# Print last 3000 chars (most useful — shows what happened before failure)
print(content[-3000:])
```

The log is JSONL with entries like:

```json
{
  "type": "notification",
  "timestamp": "...",
  "notification": { "jsonrpc": "2.0", "method": "_posthog/console", "params": { "level": "debug", "message": "..." } }
}
```

Key things to look for in the log tail:

- **agentsh network events** — `DENY` entries show blocked network calls
- **`_posthog/progress`** events — show which setup step the sandbox reached
- **`_posthog/console`** debug messages — show sandbox provisioning, cloning, agent startup

## Inspecting Docker sandbox containers

```bash
# List running sandbox containers
docker ps --filter "name=task-sandbox" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

# See processes inside a running sandbox
docker exec <container-name> ps aux

# Read the agent-server log inside the container (while it's still running)
docker exec <container-name> cat /tmp/agent-server.log
```

The container is named `task-sandbox-<task-id>-<random>` and uses the `posthog-sandbox-base` image.
Containers are ephemeral — they're removed after the task run completes, so inspect while running.

## Common failures

### `SignalReport matching query does not exist`

The `assign_and_emit_signal_activity` tried to assign a signal to a report that doesn't exist.
Usually caused by stale embeddings in ClickHouse after a `cleanup_signals` that failed to delete them.

**Root cause:** `CLICKHOUSE_DATABASE` not set in `.env`. The cleanup command uses `sync_execute`
which connects to the `CLICKHOUSE_DATABASE` (defaults to `default`), but the embedding tables
live in the `posthog` database.

**Fix:** Add `CLICKHOUSE_DATABASE=posthog` to `.env` and restart workers.

**Manual cleanup of stale embeddings:**

```bash
curl -s 'http://localhost:8123/' --data-binary \
  "ALTER TABLE posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536 DELETE WHERE product = 'signals' AND team_id = 1 SETTINGS mutations_sync = 1"
```

**Verify embeddings are clean:**

```bash
curl -s 'http://localhost:8123/' --data-binary \
  "SELECT count() FROM posthog.sharded_posthog_document_embeddings_text_embedding_3_small_1536 WHERE team_id = 1 AND product = 'signals'"
```

### `Run timed out due to inactivity` on `select_repository_activity`

The sandbox Claude agent went idle for longer than `TASKS_INACTIVITY_TIMEOUT_SECONDS`. When unset
this falls back to a 2 hour timeout — set `TASKS_INACTIVITY_TIMEOUT_SECONDS=30` locally to force fast failures.

**Diagnosing:** Read the agent log from object storage (see above). Check the tail for:

1. **agentsh network denials** — `DENY host.docker.internal` means the MCP server URL is blocked
   by the sandbox network policy. The `SIGNALS_REPO_DISCOVERY` environment's domain allowlist
   doesn't include `host.docker.internal`.
2. **No log content at all** — sandbox failed to start, check Docker container logs.
3. **Claude API errors** — check if `ANTHROPIC_API_KEY` is valid.

### `buffer-signals` sits idle, never receives signals

The `signal-emitter` completed but `buffer-signals` never got the `submit_signal`.
This happens when the emitter sent the signal to a previous buffer run that then continued-as-new,
and the new run started fresh without the pending signal. Re-emit the signal.

### ClickHouse embedding tables "not found" during cleanup

The tables exist in the `posthog` database but `sync_execute` queries the `default` database.

```bash
# Verify tables exist
curl -s 'http://localhost:8123/' --data-binary "SHOW TABLES FROM posthog LIKE '%embed%'"

# Check current CLICKHOUSE_DATABASE setting
grep CLICKHOUSE_DATABASE .env
```

## Useful management commands

| Command                                            | Purpose                                        |
| -------------------------------------------------- | ---------------------------------------------- |
| `emit_signals_from_fixture`                        | Emit test signals from JSON fixtures           |
| `DEBUG=1 cleanup_signals --team-id N --yes`        | Delete all signal data and terminate workflows |
| `signal_pipeline_status --team-id N --wait`        | Wait for pipeline to finish processing         |
| `list_signal_reports --team-id N --signals --json` | Inspect grouping results                       |
| `ingest_signals_json <file> --team-id N`           | Ingest pre-processed signals from JSON         |
| `ingest_report_json <file> --team-id N`            | Seed a pre-researched report (skip sandbox)    |

## Key file locations

- Pipeline workflow definitions: `products/signals/backend/temporal/`
- Buffer workflow: `products/signals/backend/temporal/buffer.py`
- Grouping workflow: `products/signals/backend/temporal/grouping_v2.py`
- Report summary workflow: `products/signals/backend/temporal/summary.py`
- Docker sandbox implementation: `products/tasks/backend/logic/services/docker_sandbox.py`
- Sandbox Dockerfiles: `products/tasks/backend/sandbox/images/`
- Agent log polling: `products/tasks/backend/logic/services/custom_prompt_internals.py`
- Cleanup command: `products/signals/backend/management/commands/cleanup_signals.py`
- Management command docs: `products/signals/backend/management/CLAUDE.md`
