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

## MinIO bucket doesn't exist yet (local dev only)

**Symptom:** the CLI's first S3 write (`Workspace.write_spec`, `prepare-from-hogql`)
exits with `AWS Error NO_SUCH_BUCKET during CreateMultipartUpload operation`.

**Cause:** local-dev MinIO doesn't seed the `automl` bucket. The bucket has to
exist before the workspace lands its first file.

**Fix (one-shot, expected on a fresh local stack):** the CLI's `pyarrow.fs.S3FileSystem`
has `allow_bucket_creation=True`. Create it before retrying:

```python
import pyarrow.fs as pa_fs
fs = pa_fs.S3FileSystem(
    endpoint_override="host.docker.internal:19000",
    scheme="http",
    allow_bucket_creation=True,
)
fs.create_dir("automl")
```

Then retry the failing CLI command. Production won't hit this — real AWS S3
buckets are pre-provisioned in infra.

## AWS credentials not exported

**Symptom:** S3 writes fail with `AWS Error NETWORK_CONNECTION` or 403, even
after the bucket exists.

**Cause:** the CLI's S3 paths read `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
/ `AWS_DEFAULT_REGION` from env. The bootstrap brief's Run context block
carries the local-dev MinIO values — you have to `export` them at the start
of each shell session before any CLI invocation that touches `s3://`.

```bash
export AWS_ACCESS_KEY_ID=$aws_access_key_id
export AWS_SECRET_ACCESS_KEY=$aws_secret_access_key
export AWS_DEFAULT_REGION=$aws_default_region
```

(Values come from the Run context JSON block — don't hardcode them in your
shell history.)

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
