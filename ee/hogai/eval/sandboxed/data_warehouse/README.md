# Data-warehouse sandboxed evals

Evals for the data-tools MCP surface — primarily `execute-sql` and the
HogQL it produces. Owned by the data-tools team (SQL editor, notebooks,
HogQL).

## What's covered

| File                      | What it asserts                                                                                           |
| ------------------------- | --------------------------------------------------------------------------------------------------------- |
| `eval_sql_recovery.py`    | Agent recovers from a broken HogQL query (typoed column, wrong-case function) without user nudging.       |
| `eval_sql_correctness.py` | Agent's HogQL actually returns a number consistent with the Hedgebox demo seed (counts, joins, group-by). |
| `eval_sql_regressions.py` | Pinned coverage for HogQL features we don't want silently regressing. Grow this file as fixes land.       |

## How it relates to neighbouring suites

- `cli_mcp/eval_workflow.py` (skoob13, #57472) grades workflow shape
  ("did the agent verify schema _before_ querying?"). This folder grades
  the layer underneath — _what answer came back_. The two are
  complementary; cases in both folders should run together as part of a
  full sweep.
- `product_analytics/` grades structured `query-<insight>` output. We
  grade free-form HogQL output. Different tools, different scorers.

## Scorers

`scorers.py` exports `HogQLOutputMatches`. Per the convention introduced
in #57472, the spec lives under `expected[scorer_name]`:

```python
SandboxedEvalCase(
    name="...",
    prompt="...",
    expected={
        "hogql_output_matches": {
            # Pick one:
            "value": 1234,                 # exact
            "min": 100, "max": 100_000,    # inclusive range
            "non_zero": True,              # any positive number
            "regex": r"\bdocs\b",          # text match (case-insensitive)
            # Optional alongside `value`:
            "tolerance": 0.5,
        }
    },
)
```

The scorer searches both the last successful `execute-sql` tool output
and the agent's final user-facing message. Either matching counts as a
pass.

`ExitCodeZero` and `RequiredToolCall` come from the shared
`ee/hogai/eval/sandboxed/scorers/` package — reuse, don't duplicate.

## Running

The sandboxed harness boots a real `services/mcp/` worker, real LLM
gateway, in-process Django, in-process Temporal, and Docker sandbox
containers per case. First run takes a couple of minutes to seed the
master Hedgebox team; subsequent runs reuse it via `--reuse-db`.

```bash
# Single file
pytest ee/hogai/eval/sandboxed/data_warehouse/eval_sql_recovery.py

# Single case
pytest ee/hogai/eval/sandboxed/data_warehouse/eval_sql_recovery.py \
    --eval=recovery_misspelled_column

# Whole folder, both MCP modes (tools + cli) — defaults from conftest
pytest ee/hogai/eval/sandboxed/data_warehouse/

# Pin a single MCP mode
pytest ee/hogai/eval/sandboxed/data_warehouse/ --mcp-mode=tools
```

`BRAINTRUST_API_KEY` and `OPENAI_API_KEY` must be set — the harness
calls `EvalAsync` which logs into Braintrust at experiment-init time,
and the tracing wrapper eagerly constructs an OpenAI client even when
no scorer uses it. Get a real Braintrust key from `#team-posthog-ai`;
`OPENAI_API_KEY=sk-not-used` is fine for deterministic-only suites
since the client is never actually invoked.

## Calibrating expected values

Hedgebox's seed includes randomised simulation steps, so absolute counts
shift slightly run-over-run. Cases in `eval_sql_correctness.py` use
loose ranges (`min`/`max` or `non_zero`) deliberately — the goal is
"the query returned the right _shape_ of answer", not "the count is
exactly N".

To tighten a range:

1. Run the case once and inspect the local logs at
   `ee/hogai/eval/sandboxed/.eval-logs/<experiment>/<case>/` — the
   `last_message` and tool-call output show the actual number the agent
   surfaced.
2. Pick a range generous enough to absorb seed jitter (±20% is usually
   fine) but tight enough to catch wrong-query bugs.
3. Update `expected["hogql_output_matches"]` and re-run.

Don't pin `value=N` exact-match unless you've confirmed the count is
deterministic across re-seeds — for most demo-data questions, a range
or `non_zero` is the right tool.

## Adding a regression pin

When a HogQL fix lands that we want to lock in:

1. Add a `SandboxedEvalCase` to `eval_sql_regressions.py`.
2. The prompt should _only_ succeed if the fixed behaviour holds —
   ideally a query that erred or returned wrong results before the fix.
3. Add a comment with the fix PR number so future readers know what the
   pin is protecting.
4. Use `HogQLOutputMatches` with a tight bound (the deterministic answer
   the fix unlocks).

## Deferred

- **Notebooks tools** — current MCP tools are thin CRUD passthroughs;
  no agent intelligence to grade. Revisit when smarter tools land
  (insert HogQL block, run cell).
- **Saved views workflow** (`view-create` → `view-run` →
  `view-materialize`) — interesting because it's stateful and
  multi-step, but lower priority than `execute-sql` semantic
  correctness.
- **SQL variables** — niche, low traffic.
- **External-data-sources / pipeline health** — owned by the
  warehouse-imports team, not data-tools.
