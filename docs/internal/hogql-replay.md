# HogQL replay

HogQL replay checks a pull request against queries that customers ran recently.
It compiles each logged query with the base code and with the pull request's code, runs the ones whose ClickHouse SQL changed, and reports where results or cost differ.
The result is advisory.
It is evidence over a sample, not a proof.

## Run it

```bash
hogli replay:hogql --pr 12345
hogli replay:hogql --pr 12345 --query-id <query_log_archive query ID> --query-id <another>
```

Without `--query-id` it samples 200 queries from the last 7 days.
A query ID must be from the last 30 days.
Change the size with `--sample`.

You need Tailscale, a `prod-us` kubernetes context, and an image for the pull request from Container Images CI.
The command claims two pods from the `posthog-hogql-replay` pool, puts the pull request's image on one, and deletes both when it finishes.
The pool only has read access to Postgres and ClickHouse.
Both images must contain the `hogql_replay` command, so rebase a pull request that branched before the command existed.

The command writes `result.json` and `index.html` to `hogql-replay-report/`.
With the `hosthog` CLI installed it also publishes the HTML report for employees.
Pass `--no-publish` to keep it local.

For every query whose SQL changed, the report keeps both versions as files: `sql/<query ID>.base.sql` and `sql/<query ID>.head.sql`.
`result.json` names them in `base_sql_file` and `head_sql_file`.
Each file is complete ClickHouse SQL with its dates fixed, so you can run both and compare the rows yourself, for example with the `/query-clickhouse-via-metabase` skill.

The report contains customer query text.
Do not paste it into a pull request, an issue, or any public place.

## Verdicts

| Verdict             | Meaning                                                                                  |
| ------------------- | ---------------------------------------------------------------------------------------- |
| `identical_sql`     | Base and head compile to the same SQL. Not run.                                          |
| `same_results`      | The SQL changed and the results match.                                                   |
| `different_results` | The SQL changed and the results differ.                                                  |
| `head_only_error`   | The base works and the head fails to compile or run.                                     |
| `unstable`          | Two runs of the base disagree. Not judged.                                               |
| `could_not_model`   | The base compile does not match the SQL that production ran. Not judged.                 |
| `not_run`           | The base failed to run, or the run was over the cap of 200 executed queries. Not judged. |

A query is a cost regression when the head reads more than 1.5 times the bytes of the base.

The report names the exact image each pod ran.
The pull request image tag moves with every push, so check that the head image is the build you expect.

## What it does not check

- Changes to how a query runner shapes its response in Python. Only ClickHouse rows are compared.
- Query runners that send more than one statement to ClickHouse. These show as `could_not_model`.
- Requests that sent more than one statement in production, and queries logged without a client query ID. These are left out of the sample.
- Row order. Results are compared as a set of rows with a row count.
- The EU region.

## How it works

The management command `hogql_replay` has three actions, and `hogli replay:hogql` runs them in the pods.

1. `sample` reads query IDs or a sample from `query_log_archive`.
2. `compile` runs in both pods. It builds each query through its query runner at the time the query originally ran, and records the SQL without sending it to ClickHouse.
3. `run` runs in the base pod. It runs the base SQL twice and the head SQL once, compares row count and a hash of the rows, and reads the bytes each run read from the query log.
