# Common pitfalls (PostHog-side)

Failure modes specific to the PostHog brief / MCP / sandbox boundary. The
CLI's own four skills carry pitfalls catalogs for ML-side issues (HogQL
precedence, near-constant features, leakage, time-budget tuning) — read
those when the CLI errors. This catalog is just the boundary issues.

## `config.target` vs `config.target_event`

These are deliberately different concepts and the brief's pipeline spec
has both:

- `config.target_event` is the **PostHog event name** (e.g., `upgraded_plan`).
  The validator uses it for base-rate sizing and leakage checks before the
  pipeline runs.
- `config.target` is the **column name in the training snapshot** (e.g.,
  `target`, `upgraded_in_14d`). The trainer reads this as the label column.

Your SELECT clause must produce a column named exactly `config.target`. The
`--target` flag on `automl train` takes the column name, not the event name.

**Symptom:** `train` exits 1 with `KeyError: <target>` or "target column not
found in dataframe".

**Fix:** add an `AS <config.target>` on the label expression in the SELECT
clause, or rename the existing label column to match.

## Row-count floor (200 rows)

**Symptom:** `prepare-from-hogql` succeeded but returned fewer than 200 rows.

**Decision rule:** below 200 rows a binary classifier doesn't generalize
reliably and AutoGluon's stratified split + cross-validation routines start
to misbehave. **Stop with `failure_reason=population_too_small`** — surface
the row count and the likely cause (horizon-eligibility filter, JOIN keys,
target event genuinely rare). Do not proceed to training.

This is a hackathon-grade threshold. Production raises it once we have
realistic data volumes.

## MCP tools advertise as missing

**Symptom:** `mcp tools | grep automl` returns no entries, or a specific
`automl-*` tool call returns "tool not found", or `automl-record-eda-result` /
`automl-record-bootstrap-outcome` is unknown.

**Cause:** the local MCP server's `services/mcp/src/generated/automl/api.ts`
is stale (missing newly added tools). The local MCP server fails to start
or skips registering the automl tools.

**Fix:** not recoverable from inside the sandbox. Surface the missing tool
name in your outcome report and stop with `failure_reason=mcp_unavailable`.
The user needs to re-run `hogli build:openapi` and restart the MCP server
on the host.

## Untagged-query errors from the HogQL API

**Symptom:** the HogQL API returns a 500 with an `UntaggedQueryError` mention.

**Cause:** PostHog requires every ClickHouse query to be tagged with a
`product` + `feature` for observability. The `prepare-from-hogql` path goes
through the public `/query/` endpoint which does its own tagging — you should
not hit this. If you do, it's a server-side bug.

**Fix:** surface the trace in your outcome report and stop with
`failure_reason=snapshot_fetch_failed`. Not recoverable from inside.

## Sandbox-credential issues

**Symptom:** `prepare-from-hogql` or an MCP tool returns 401.

**Cause:** `POSTHOG_PERSONAL_API_KEY` is OAuth-issued at sandbox provisioning;
it may have expired, been issued for a different team, or be missing the
`automl:read` / `automl:write` scope.

You cannot recover this from inside the sandbox. Surface the 401 body in
your outcome report and stop with `failure_reason=snapshot_fetch_failed`
(for HogQL 401) or `failure_reason=mcp_unavailable` (for MCP 401).
