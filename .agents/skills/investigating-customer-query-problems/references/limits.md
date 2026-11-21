# Where query limits live

This file says where each limit is set and how to see its value in prod. It does not record values, because they change.

Before you state a limit, in Slack, a handoff, or your own reasoning:

1. Read it from prod when the table gives a way. Prod shows what actually ran.
2. Otherwise read the code on current master, not the working tree, which may be an old branch: `git fetch origin master`, then `git grep -n '<symbol>' origin/master -- <path>`. If the symbol moved, `git grep` without the path.
3. Put the source next to the number when you write it down (file and line, or the query).

## Telling the paths apart in `posthog.query_log_archive`

Read the header comment of `posthog/clickhouse/query_log_archive.py` on `origin/master` for what one row means. When a row is a whole query chain (`initial_query_id`), counters such as CPU and `read_bytes` are summed over every node, and descriptive columns come from the initial query. List the current columns with `SELECT name FROM system.columns WHERE database = 'posthog' AND table = 'query_log_archive'`.

| Column                                                                    | Use                                                                                        |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `lc_access_method`                                                        | `personal_api_key`, `oauth`, and the other values in `posthog/clickhouse/query_tagging.py` |
| `lc_feature`                                                              | `mcp` for MCP tools                                                                        |
| `lc_kind`                                                                 | `request` (sync), `celery` (ran in a Celery task), `temporal`                              |
| `lc_workload`                                                             | workload the query was routed to                                                           |
| `lc_api_key_label`, `lc_route_id`, `lc_client_query_id`, `lc_name`        | which key, route, and client job sent it                                                   |
| `lc_query__kind`, `lc_query__query`                                       | query kind and the HogQL text the customer sent                                            |
| `hogql_shape`, `query_shape`, `normalized_query_hash`                     | the HogQL text and compiled SQL with literals stripped. Group jobs by these.               |
| `user`                                                                    | ClickHouse user the chain ran as                                                           |
| `execution_count`                                                         | rows in the chain, so it shows fan-out over long windows                                   |
| `ProfileEvents_OSCPUVirtualTimeMicroseconds`, `read_bytes`, `result_rows` | cost and output                                                                            |

Fields the archive lacks, such as `log_comment` keys like `execution_mode`, per-node rows, and `hostName()`, come from live `clusterAllReplicas(posthog, system, query_log)` over a short window.

## Time caps

| Path                    | Where it is set                                                                                                                                                                                                                                                    | See it in prod                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| Personal API key, sync  | `posthog/hogql_queries/hogql_query_runner.py`, the `max_execution_time` assignment next to `API_QUERIES_LEGACY_TEAM_LIST`                                                                                                                                          | `extract(query, 'max_execution_time=(\\d+)')` grouped by `lc_kind` |
| Personal API key, async | the `LimitContext` that `enqueue_process_query_task` passes (`posthog/clickhouse/client/execute_async.py`), what `_effective_direct_settings` does with it (`posthog/hogql/query.py`), and the sync path's choice in `posthog/api/query.py` (search `QUERY_ASYNC`) | same extract with `lc_kind = 'celery'`                             |
| MCP and PostHog AI      | callers of `LimitContext.POSTHOG_AI` (`git grep -n 'LimitContext.POSTHOG_AI'`)                                                                                                                                                                                     | same extract with `lc_feature = 'mcp'`                             |
| Endpoint run            | `products/endpoints/backend/logic/execution.py`, what it passes as `is_query_service`, then the runner cap above                                                                                                                                                   | same extract on the endpoint's runs                                |

| Kill switch, global or per team | `KillSwitchLevel` settings and `get_team_kill_switch_level` in `posthog/clickhouse/client/execute.py`. It lowers the time cap and concurrency while it is on. | a `max_execution_time` in the compiled SQL that differs from the path's usual value |

Check this every time: does the async path give API key queries a longer cap than sync? If it does, the sync path's deliberate choice suggests that's a gap. Report it internally and don't advise customers to use async to get around the sync cap.

## Row caps

| What                                                        | Where it is set                                                                                                | See it in prod                                                                |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Default rows when the query has no `LIMIT`, and the maximum | `get_default_limit_for_context` and `get_max_limit_for_context` in `posthog/hogql/constants.py`                | the `LIMIT` in the compiled `query`, and `result_rows` piling up at one value |
| Which context a path uses                                   | `LimitContext.` in that path's entry point (`posthog/api/query.py`, `execute_async.py`, the AI query executor) | same                                                                          |
| Endpoint paging                                             | `products/endpoints/backend/logic/pagination.py`                                                               | n/a                                                                           |

## Concurrency and throttles

| What                                                                                   | Where it is set                                                                                                                                                             | See it in prod                                                                                                          |
| -------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| ClickHouse user limit for MCP and AI (`max_concurrent_queries_for_user`)               | posthog-cloud-infra, not this repo. The user is picked in `posthog/clickhouse/client/execute.py`.                                                                           | the `exception` text of a code 202 row (archive or live `query_log`) names the user, the current count, and the maximum |
| Our Redis limiters (`api_per_team`, `app_per_org`, materialized endpoints, and others) | `posthog/clickhouse/client/limit.py`, search `limit_name=`. Overrides come from settings such as `API_QUERIES_PER_TEAM`, plan entitlements, and the ClickHouse kill switch. | Prometheus `posthog_clickhouse_query_concurrency_limit_exceeded`, whose `limit` label is the value that was applied     |
| Which cluster a path runs on                                                           | workload routing in `posthog/clickhouse/client/execute.py` (search `Workload.OFFLINE`), and what each URL points to per region in `posthog/settings/data_stores.py`         | `hostName()` of the team's rows in live `query_log`. The cluster decides which per-node user limit applies.             |
| Request throttles                                                                      | `get_throttles` in `posthog/api/query.py`, and the classes in `posthog/rate_limit.py`                                                                                       | not in `query_log`, because throttled requests never reach ClickHouse                                                   |

Check whether async status polls count against the same throttle by reading `get_throttles` for the poll route.

Async tasks retry capacity errors (`autoretry_for` in `posthog/tasks/tasks.py`), so one failure the user sees can be several 202 rows. Count requests as well as rows, for example `uniqExact(lc_client_query_id)`. Check that the ID stays the same across retries first.

## Result cache

| What                                   | Where it is set                                                                                                                                                                                                                                                                                                                                                              | See it in prod                                                                 |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| How long a SQL result stays fresh      | `_is_stale` in `posthog/hogql_queries/hogql_query_runner.py` and the base `_is_stale` in `query_runner.py`, with the interval it falls back to in `posthog/interval_specs.py`. Check for team flags that change it, such as `API_SQL_WINDOW_CACHE_AGE_FLAG`, and whether this team has them. `cache_target_age` sets the stored target age, not the freshness used for hits. | gaps between identical runs that still reach ClickHouse (queries.md section 8) |
| Past-dated results that never go stale | `is_stale` in `posthog/caching/utils.py`. Check whether SQL queries can reach that rule.                                                                                                                                                                                                                                                                                     | n/a                                                                            |
| Refresh mode                           | `execution_mode_from_refresh` in `posthog/hogql_queries/query_runner.py`                                                                                                                                                                                                                                                                                                     | `JSONExtractString(log_comment, 'execution_mode')` in live `query_log`         |

## Materialization

| What                                                               | Where it is set                                                                                                                                                                                       |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What an endpoint can materialize                                   | `can_materialize_query` in `products/endpoints/backend/models.py`, and `_cte_join_rejection` in `products/endpoints/backend/materialization_transforms.py`                                            |
| Endpoint freshness choices                                         | `DATA_FRESHNESS_BUCKET_SPECS` in `products/endpoints/backend/constants.py`                                                                                                                            |
| Where view refreshes run, and whether they are full or incremental | `posthog/temporal/data_modeling/activities/materialize_view.py` (search `CLICKHOUSE_OFFLINE_HTTP_URL` and `incremental`), and what that URL points to per region in `posthog/settings/data_stores.py` |

## ClickHouse error codes

These come from ClickHouse, not PostHog code. Read `exception_name` in `query_log` when unsure.

| Code | Name                          |
| ---- | ----------------------------- |
| 159  | TIMEOUT_EXCEEDED              |
| 160  | TOO_SLOW                      |
| 202  | TOO_MANY_SIMULTANEOUS_QUERIES |
| 241  | MEMORY_LIMIT_EXCEEDED         |
| 439  | CANNOT_SCHEDULE_TASK          |

Which codes surface to users as `ClickHouseAtCapacity` is decided in `posthog/errors.py` (search `ClickHouseAtCapacity`).
