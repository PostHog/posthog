# Data Catalog scripts

## Semantic-layer canary

`semantic_layer_canary.py` is the local runner for the Data Catalog semantic-layer canary. A local ChatGPT session invokes the script on demand or from its daily workflow. The runner itself does not use Dagster or a server-side scheduler; a separate Signals Scout scores the resulting task runs.

The runner reads a pinned revision of a PostHog LLM Analytics dataset, opens each enabled question through the task-backed PostHog Conversations API, waits for the agent turn to finish, and writes task/run correlation metadata for later inspection. It does not evaluate answers or publish PostHog events.

### Access

The runner authenticates through a dedicated PostHog browser session because the task-backed Conversations endpoint uses web-session authentication. It does not use a personal API key.

Create the reusable browser profile once:

```bash
flox activate -- .venv/bin/python products/data_catalog/scripts/semantic_layer_canary.py --browser-login
```

A dedicated Chrome window opens. Sign in to PostHog and leave the window open until the command confirms authentication. The profile is stored at `.context/semantic-layer-canary-browser` by default and is reused by headless runs. The browser helper returns only the session and CSRF cookies directly to the runner in process memory; they are never included in the command, output, dataset item, or workflow response.

If a run reports `auth_required`, repeat the login command and retry the original run. For an interactive run, `--browser-login-if-needed` can open the login window automatically when the saved session has expired. Do not use that option in an unattended workflow because it waits for a person to complete login.

The defaults target `https://us.posthog.com`, project `2`, and dataset `semantic-layer-canaries-v1`. Override the host or project explicitly when needed.

### Dataset contract

Each dataset item must use this shape:

```json
{
  "input": {
    "question": "Show weekly widget activations for the last quarter.",
    "agent_mode": "product_analytics"
  },
  "expected_output": {
    "expected_metric": "Weekly widget activations",
    "expected_routing": "canonical_metric",
    "expected_behavior": "Run the approved metric and summarize its output."
  },
  "metadata": {
    "case_id": "direct-canonical-mrr",
    "category": "direct_match",
    "enabled": true
  }
}
```

`agent_mode` accepts `product_analytics` or `sql` as expectation metadata for existing dataset revisions. The task-backed runtime chooses its own tools, so the runner does not send this legacy field to the Conversations API. A negative control can set `expected_metric` to `null`. `case_id` must be unique among the enabled items of the selected revision. Disabled items remain in the versioned dataset but do not run.

### Run from local ChatGPT

Ask ChatGPT to run this command from the PostHog repository:

```bash
flox activate -- .venv/bin/python products/data_catalog/scripts/semantic_layer_canary.py \
  --case 01 \
  --case 21 \
  --case 38 \
  --output .context/semantic-layer-canary-smoke.json
```

Remove the `--case` options to run every enabled item. Use `--revision N` to replay an exact historical dataset revision. The default concurrency is three and the default is one retry per case:

```bash
flox activate -- .venv/bin/python products/data_catalog/scripts/semantic_layer_canary.py \
  --revision 7 \
  --max-concurrency 3 \
  --max-attempts 2 \
  --output .context/semantic-layer-canary.json
```

The command exits with zero only when every case completes. It exits with one for partial runs, failed runs, invalid dataset contents, missing cases, or API/configuration errors.

### Output and inspection

The JSON output contains the run ID, pinned dataset revision, expected routing metadata, duration, status, conversation/trace correlation IDs, task ID, task-run ID, and direct task URLs. Failed attempts retain their task correlation when the open request succeeded. An agent failure starts a fresh attempt with new correlation and task IDs. An open request that fails before it returns a response is different: the retry reuses the same conversation ID, so a task the server created before the failure is resumed instead of duplicated. Stream rotation or a dropped connection resumes the same task run with `Last-Event-ID` and never resends the question.

A turn completes when the task stream emits `_posthog/turn_complete`, asks a structured clarification question, or reaches a terminal completed state. Other permission requests and terminal failed/cancelled states fail the attempt. PostHog AI tasks remain open briefly for interactive follow-ups after a successful turn; the runner does not cancel them.

Questions, assistant answers, streamed failure content, and exception messages are deliberately excluded from the output. Inspect the task run and its ACP session logs in PostHog to verify metric routing and answer quality. Keep local output under `.context/`, which is gitignored.
