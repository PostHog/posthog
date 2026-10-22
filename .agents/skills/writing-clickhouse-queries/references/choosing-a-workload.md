# Choosing a ClickHouse workload

Every ClickHouse call takes a `Workload` from [`posthog/clickhouse/workload.py`](../../../../posthog/clickhouse/workload.py):
`sync_execute(..., workload=)`, `execute_hogql_query(..., workload=)`, and `QueryRunner(..., workload=)`.
The workload sets two things:
the cluster the query runs on, and the `workload` query tag that `query_log_archive.lc_workload` records.
Both feed capacity planning, so pick the workload on purpose.

## The rule

- Pass `workload=` explicitly at every new call site.
  Do not rely on `Workload.DEFAULT`, unless the code runs both in a request and in the background and must follow its caller.
- Say which workload you picked and why in the PR description.
  If the reason is not clear from where the code runs, add a one-line comment at the call site, for example
  `workload=Workload.OFFLINE,  # nightly recompute, no user waits for the result`.
- When you review a diff that adds a ClickHouse call, check that its workload matches the questions below.

## Pick the workload

Answer in order and stop at the first yes.

| Question                                                                        | Workload             |
| ------------------------------------------------------------------------------- | -------------------- |
| Does the query read a table that exists only on the logs cluster?               | `LOGS`               |
| Does the query execute an Endpoints (the product) request?                      | `ENDPOINTS`          |
| Does the query target the native events schema cluster?                         | `NEW_EVENTS_CLUSTER` |
| Does a person wait on screen for this result (an app request, a Max chat turn)? | `ONLINE`             |
| Anything else: scheduled, batch, export, backfill, recompute, eval, digest      | `OFFLINE`            |

`ONLINE` is for latency a person feels.
A background job does not get faster with `ONLINE`.
It competes with interactive queries for the online replicas, or it runs on the offline replicas anyway and only gets the wrong tag (see below).

`OFFLINE` turns off hedged requests, so ClickHouse does not send a second copy of a slow query to another replica.
This keeps offline load off the online replicas when the offline replicas are busy.
Latency and failure rates are higher as a result, so offline work must tolerate retries.

## How a workload resolves

`sync_execute` in [`posthog/clickhouse/client/execute.py`](../../../../posthog/clickhouse/client/execute.py) can change the workload you pass:

1. `DEFAULT` with API-key auth (personal API key, project secret key) becomes `OFFLINE`.
2. `DEFAULT` in a Celery task becomes `OFFLINE`, except cache warming (`Feature.CACHE_WARMUP`), which stays `ONLINE`.
3. `process_query_task` forces `ONLINE` for app users and `OFFLINE` for API-key users, **even when you pass a workload explicitly**. Only `LOGS` is exempt.
4. A `workload=ENDPOINTS` query tag becomes `ENDPOINTS`.
5. Any `DEFAULT` that is left becomes the process default.
   The process default is `CLICKHOUSE_DEFAULT_WORKLOAD`, which is `ONLINE` unless the deployment sets it.
   Celery switches its process default to `OFFLINE` before each task.

## The tag and the host are separate

The workload is intent.
The host comes from the environment of the pod that runs the code, in [`get_kwargs_for_client`](../../../../posthog/clickhouse/client/connection.py):

- `ONLINE` connects to `CLICKHOUSE_HOST`.
- `OFFLINE` connects to `CLICKHOUSE_OFFLINE_CLUSTER_HOST` when the deployment sets it, and to `CLICKHOUSE_HOST` when it does not.
- `LOGS`, `ENDPOINTS`, and `NEW_EVENTS_CLUSTER` connect to their own hosts.

A background worker deployment can point `CLICKHOUSE_HOST` at the offline replicas and set `CLICKHOUSE_DEFAULT_WORKLOAD=OFFLINE`.
Then `ONLINE` and `OFFLINE` from those pods both run on the offline replicas.
Passing `ONLINE` there does not move the query to the online replicas.
It only tags an offline query as online, which hides it from per-workload capacity numbers.
Moving a query between clusters is a deployment change, not a code change.

## Check where queries land

`posthog.query_log_archive` records both the intent and the host.
Group recent initial queries by `lc_workload` and by whether `hostname` is an offline node.
An `ONLINE` tag on an offline host, from a service that is not in a request path, is a mislabeled call site.
