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

To test queries of your own, write them to a file and pass `--scenario-file`.
Each line is JSON with a team ID and either HogQL text or a full query:

```json
{"team_id": 2, "query": "select count() from events where timestamp > now() - interval 1 day"}
{"team_id": 2, "query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}}
```

A scenario has no production SQL to check against, so it is compared between the base and the head only.
It runs against that team's real data.

You need Tailscale, a `prod-us` kubernetes context, and an image for the pull request from Container Images CI.
The command claims two pods from the `posthog-hogql-replay` pool, puts the pull request's image on one, and deletes both when it finishes.
The pool only has read access to Postgres and ClickHouse.
Both images must contain the `hogql_replay` command, so rebase a pull request that branched before the command existed.

The pods write the report to a private bucket, under `runs/pr-<number>/<time>/report/`.
Nothing is copied to your machine.
The command prints two links that only work on Tailscale: `index.html` for people and `result.json` for agents.
Reports are deleted after 14 days.

For every query whose SQL changed, the report keeps both versions as files: `sql/<query ID>.base.sql` and `sql/<query ID>.head.sql`.
`result.json` names them in `base_sql_file` and `head_sql_file`.
Each file is complete ClickHouse SQL with its dates fixed, so you can run both and compare the rows yourself, for example with the `/query-clickhouse-via-metabase` skill.

For a `different_results` query the report shows the first 20 rows that are only in the base and only in the head.
The same rows are in `sql/<query ID>.differences.json`, not in `result.json`.

The report contains customer query text and result rows.
Do not download it, and do not paste any of it into a pull request, an issue, or any public place.

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
- Row order. Rows are compared without regard to order, and duplicates count.
- The EU region.

## How it works

The management command `hogql_replay` has six actions, and `hogli replay:hogql` runs them in the pods.

1. `sample` reads query IDs or a sample from `query_log_archive`. `scenarios` reads your own queries instead.
2. `compile` runs in both pods. It builds each query through its query runner at the time the query originally ran, and records the SQL without sending it to ClickHouse.
3. `upload` and `download` pass the sample and the compiled SQL between the two pods through the bucket.
4. `run` runs in the base pod. It runs the base SQL twice and the head SQL once, compares the columns and the rows, and reads the bytes each run read from the query log.
   Floats match to 9 significant digits.
   A result over 10,000 rows is compared by row count and a hash of the rows.
