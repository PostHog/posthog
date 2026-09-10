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

A dedicated Chrome window opens. Sign in to PostHog and leave the window open until the command confirms authentication. The profile is stored at `.context/semantic-layer-canary-browser` by default and is reused by headless runs. That directory holds live session state, so treat it as a credential: keep it inside `.context/`, which the repository ignores, and do not copy it between machines or workspaces. The browser helper returns only the session and CSRF cookies directly to the runner in process memory; they are never included in the command, output, dataset item, or workflow response.

If a run reports `auth_required`, repeat the login command and retry the original run. For an interactive run, `--browser-login-if-needed` can open the login window automatically when the saved session has expired. Do not use that option in an unattended workflow because it waits for a person to complete login.

The defaults target `https://us.posthog.com`, project `2`, and dataset `semantic-layer-canaries-v1`. Override the host or project explicitly when needed.

### Trust boundary

The runner sends each dataset question to an agent that runs with the signed-in operator's own PostHog access, under `initial_permission_mode: auto`, with nobody reviewing tool calls. The dataset is therefore a trusted input, not user input: anyone who can edit the selected revision can direct that agent. Two consequences follow.

- Treat dataset write access to the canary dataset as equivalent to acting as the operator.
- Pin a reviewed revision with `--revision N` for an unattended run, rather than taking whichever revision is current.

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

A turn completes when the task stream emits `_posthog/turn_complete`, asks a structured clarification question, or reaches a terminal completed state. Other permission requests and terminal failed/cancelled states fail the attempt. PostHog AI tasks remain open briefly for interactive follow-ups after a successful turn; the runner does not cancel them, with one exception.

A structured clarification question parks a permission request that stays open with no timeout. Anyone or anything that answers it later resumes the agent, and the run then continues past the question the canary was measuring. So the runner records the question text on the case result and cancels that run immediately. Scoring reads `clarification_questions` on the case; an empty list means the agent never asked.

## Scoring a canary batch

`semantic_layer_canary_score.py` grades a completed batch from the full ACP session log of each run, using the same scorers as the offline evals in `products/data_catalog/evals/`. It is the only scorer. The `signals-scout-semantic-layer-canary-report` scout reports the `$ai_evaluation` events this script emits; it does not grade session logs itself. A batch that was never scored here has no pass rate anywhere.

Score the file the runner just wrote:

```bash
POSTHOG_API_KEY=phx_... flox activate -- .venv/bin/python \
  -m products.data_catalog.scripts.semantic_layer_canary_score \
  --results .context/semantic-layer-canary.json
```

Without the runner's file, rebuild the batch from the tasks the runner created. Pass the window of task creation times and the dataset revision that was run:

```bash
POSTHOG_API_KEY=phx_... flox activate -- .venv/bin/python \
  -m products.data_catalog.scripts.semantic_layer_canary_score \
  --batch 2026-09-10T16:54:23Z 2026-09-10T17:17:23Z --revision 42
```

`--batch` reads the pinned revision, then finds each enabled question's task among `origin_product=posthog_ai` tasks created inside the window. Only a task whose full description equals the question counts; there is no fuzzy matching. A case with no task in the window is `missing`; a case whose newest attempt is still running is `incomplete`; more than one completed attempt is `duplicate`; a failed attempt followed by a completed one scores the completed one. A run the runner cancelled behind a clarifying question is scored as completed, with the question text recovered from its log. The batch id is `tasks:<from>:<to>`, so scoring the same window twice publishes the same experiment id.

The personal API key needs `task:read`, plus `dataset:read` for `--batch`.

It prints one JSON verdict row per case on stdout and a batch summary on stderr. `--emit` additionally publishes an `$ai_evaluation` event per case, tagged with the batch id, and needs `POSTHOG_CAPTURE_TOKEN`. Unscored cases are emitted too, with `$ai_evaluation_applicable` false and the case status as the reasoning, so the scout can report coverage gaps without reading logs. Every event carries `task_id`, `task_run_id`, and `task_url` for the report's links.

Each case is graded against its dataset `expected_routing`:

| `expected_routing`     | Passes when                                                                                    |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| `canonical_metric`     | the catalog was consulted before any data-bearing call, and `expected_metric` ran successfully |
| `derive_from_approved` | the same, and the named metric was never run for the answer                                    |
| `clarify`              | a question was asked before any data-bearing call, and no metric ran                           |
| `no_match`             | the catalog was consulted first, and no metric ran                                             |

### What the scorer checks

The catalog tool surface is `metric-list` (paginated, no search parameter, not data-bearing), `metric-describe` (one stored definition, not data-bearing), `data-catalog-metric-run` (executes a governed metric; its response repeats `status` and `is_drifted`), and `execute-sql` over `system.information_schema.metrics`, which still counts as consulting the catalog. A data-bearing call is `execute-sql`, any `query-*` tool, `read-data-schema`, or a typed domain tool. Tool discovery (`info`, `search`, `schema`) is neither.

- `metrics_catalog_before_data_discovery`: a successful catalog lookup precedes the first data-bearing call.
- `canonical_metric_run`: `data-catalog-metric-run` ran `expected_metric` successfully, or was never called where the routing forbids it.
- `clarification_asked`: a question tool call precedes any data-bearing call.
- `proposed_metric_not_run`: a `derive_from_approved` case never executed the named proposed metric.
- `metric_describe_before_adapted_sql`: advisory, see below.

An unrecognized `expected_routing` and a run without a confirmed terminal status both come back as `unscored` rather than a guess. `metric_describe_before_adapted_sql` is advisory: it never fails a case on its own, because a run that listed the catalog and then wrote its own SQL did consult the catalog.

It reads whole logs, paginating at 5000 entries from offset zero. A partial log cannot show what a run did before the slice, so there is no tail-reading mode.

Questions, assistant answers, streamed failure content, and exception messages are deliberately excluded from the output. Inspect the task run and its ACP session logs in PostHog to verify metric routing and answer quality. Keep local output under `.context/`, which is gitignored.
