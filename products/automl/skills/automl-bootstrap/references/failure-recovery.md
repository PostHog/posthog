# Failure recovery: when to iterate, when to give up

The bootstrap workflow runs in a disposable sandbox. You have full bash access,
the CLI is on `PATH`, and the HogQL API + MCP tools are reachable. **Most
failures are recoverable** if you read the error and adjust your inputs.

## Decision framework

For each non-zero exit or 4xx response, ask:

1. **Did the error tell me what's wrong?** If yes, check the
   [common pitfalls](./common-pitfalls.md) catalog. There's a decent chance the
   answer is there.
2. **Can I fix this from inside the sandbox?** Some fixes (SQL syntax, missing
   target column, wrong CLI flag) are trivially recoverable. Others (expired
   credentials, missing bind-mount) are structural and can't be fixed here.
3. **Am I likely to succeed on retry?** If you've tried the same input twice
   and gotten the same error, stop iterating — something deeper is wrong.

## Iterate (try again with a fix)

These are all recoverable in-loop:

- **HogQL syntax / type errors** — read the response body's `detail`, adjust
  the query, re-run `prepare-from-hogql`.
- **Missing `--target` column** — fix the SELECT clause to alias the label as
  the expected column name.
- **Empty result** — verify the population's existence with a simpler
  HogQL count; if it's actually a horizon-eligibility issue, adjust the
  `WHERE` clause.
- **CLI usage errors** (exit code 2) — run `automl <subcommand> --help` and
  fix the flag.
- **AutoGluon "no signal" warnings** — these are informational; check the
  leaderboard before deciding to stop.

After ~3 unproductive iterations on the same step, switch tactics. Iterating
forever on the same approach is a sign you're missing something fundamental;
broaden your investigation (read the CLI source, dump the parquet header, sanity-check the schema) instead.

## Stop (you can't recover here)

- **`POSTHOG_PERSONAL_API_KEY` rejected (401).** OAuth-issued at provisioning
  time — not fixable from inside.
- **Sandbox bind-mount missing.** If `/tmp/workspace/repos/posthog/automl-cli/`
  is empty or `pyproject.toml` is missing, sandbox provisioning didn't wire it.
  Not fixable from inside.
- **Training population is genuinely too small** (you've verified the count
  via HogQL and it's below 1000). The user needs more data; bootstrap can't
  proceed.
- **AutoGluon crashes on clean data.** If the parquet schema looks right
  (verified via `python3 -c "import polars; print(polars.read_parquet('./training_snapshot.parquet').describe())"`) and AutoGluon still errors, it's a CLI / dep bug. Surface the stderr tail and stop.
- **MCP tool returns a 5xx repeatedly.** Recoverable on the server side, not
  in-sandbox. Stop and surface the trace.

## What to write when you stop

Whether you succeeded or stopped, your final message is the **outcome report**
(see step 7 in the main skill). When stopping early:

- Include `**Verdict**: failed`
- Explain what step you got to, what you tried, and why you stopped
- Include the relevant error response bodies (HogQL JSON, CLI stderr tail) so
  the user can act on them
- Don't emit a specific error code — the workflow has full visibility into
  your bash invocations and structured output

The user reads this on the pipeline detail page. Be specific enough that they
can either fix the underlying issue (data, credentials, query) or file a bug
against the CLI / brief / sandbox.
