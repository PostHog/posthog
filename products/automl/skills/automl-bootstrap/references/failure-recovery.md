# Failure recovery (PostHog-side)

The bootstrap workflow runs in a disposable sandbox. You have full bash
access, the CLI's `--help` is up to date, the MCP tools are reachable
(usually), and the HogQL API returns structured error bodies. **Most
failures are recoverable** — read the error, adjust your inputs, retry.

The CLI's four skills cover ML-side iteration (HogQL syntax, leakage,
EDA-driven feature drops, time-budget tuning). This doc covers only the
PostHog boundary failures and the terminal-stop decision framework.

## Iterate (recoverable from inside the sandbox)

These all have iteration paths via the CLI's own skills — read those first:

- **HogQL syntax / type errors** → CLI's `tune-hogql-query`
- **Empty / too-few rows above the 200 floor** → CLI's `tune-hogql-query`
  - verify the population count with a simpler HogQL query
- **Suspect leakage features** → CLI's `eda-on-features`
- **AutoGluon "no signal" warnings** → CLI's `run-train-predict` covers
  time-budget tuning + leaderboard interpretation
- **`KeyError: <target>` in train** → see `config.target` vs `config.target_event`
  in [common pitfalls](./common-pitfalls.md) and `AS <target>` your SELECT

After ~3 unproductive iterations on the same step, switch tactics rather
than burning the budget on the same approach. The CLI source is readable
(`/tmp/workspace/repos/posthog/automl-cli/backend/`) — when in doubt, grep it.

## Stop (terminate with a structured failure)

Call `automl-record-bootstrap-outcome` with `status=failed` and one of these
`failure_reason` tags. Pick the most specific one — it's how the user knows
where to look:

| `failure_reason`        | When                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mcp_unavailable`       | An MCP tool is unreachable (5xx, 404 on a tool that should exist, or `mcp tools` returns no automl entries). Server-side fix on the host.                     |
| `snapshot_fetch_failed` | `POSTHOG_PERSONAL_API_KEY` is rejected (401), the HogQL API repeatedly 5xx's, or the validator's untagged-query error surfaces.                               |
| `population_too_small`  | You've verified the row count via HogQL and it's below the 200-row floor. The user needs more data.                                                           |
| `training_crash`        | AutoGluon errors on clean parquet (you verified the schema via `polars.read_parquet(...).describe()` and it looks structurally fine). Likely a CLI / dep bug. |
| `task_create_failed`    | (Set by the surrounding workflow, not you. If you ever see this it means your run row was opened before your sandbox came up.)                                |

## When `automl-record-bootstrap-outcome` itself fails

You may hit a case where the MCP server returns "Tool exec not found" or a
similar registry-level error specifically on the outcome call (transient
workerd / wrangler hot-reload glitch). The recovery tool is the very tool
that's broken.

**What to do:**

1. Retry once after ~5 seconds — most workerd reloads finish that fast.
2. If retry still fails, **emit the outcome report markdown as your final
   message** anyway. The workflow has full visibility into your bash + MCP
   trace; the operator can read the report from the agent transcript and
   manually reconcile the run row via the facade.
3. Don't burn cycles re-querying the MCP `tools` list — if `exec` is missing,
   the whole MCP surface is degraded and re-querying won't help.

The pipeline-detail page will show the run row as `status=running` until
reconciled. That's not great UX but it's recoverable — operators close it
out by calling `record_bootstrap_outcome` directly via the facade or DRF
once MCP is healthy again. (See the manual reconciliation snippet at the
bottom of this file.)

## Manual run-row reconciliation (operator-side)

When an agent run completed successfully but couldn't record the outcome
(MCP transient failure, or the surrounding workflow ran out of budget mid-call),
the run row stays in `status=running` with empty `outcome_report`. An
operator can flip it by hand:

```python
# From the host, in a Django shell with team_scope:
from posthog.models.scoping import team_scope
from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import RunStatus
import uuid

with team_scope(<team_id>):
    api.record_bootstrap_outcome(
        team_id=<team_id>,
        run_id=uuid.UUID("<the run id>"),
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.SUCCEEDED,  # or FAILED / ABORTED
            outcome_report="...",         # copy from agent transcript
            failure_reason="",            # set if status != SUCCEEDED
            cli_run_id="<from agent>",
            agent_session_id="<from agent>",
        ),
    )
```

Calling `record_bootstrap_outcome` is idempotent on terminal state — running
it twice is a no-op the second time.

## What to write in the outcome report when you stop

The outcome report markdown body is what the user reads on the
pipeline-detail page. Be specific:

- Which CLI step you reached and what you tried before stopping
- The relevant error response body (HogQL JSON, CLI stderr tail, MCP 4xx body)
- A plain-English diagnosis of why retry won't help
- A pointer to what the user needs to do next (fix data, rotate credentials,
  restart MCP, file a bug)

Don't emit machine-readable error codes — the structured `failure_reason` is
the machine-readable handle, and the markdown body is the human-readable
explanation. They're complementary, not redundant.
