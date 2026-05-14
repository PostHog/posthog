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
