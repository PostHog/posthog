# Query execution v2

A proposal to replace the orchestration around query execution: how a request decides whether a
cached result will do, whether to compute, who waits, and how a caller gets the answer.

It does not change what a query _is_ — the SQL a runner builds, HogQL, ClickHouse access, the
cache storage format, the failure breaker, or concurrency limits. Those work.

Every claim below cites the code it rests on. A note at the end says what was checked and what was
not.

## Part 1: where the orchestration actually lives

**Inside `QueryRunner`.** That is the finding that shapes everything else.

`QueryRunner.run()` is not a thin entry point. It is the state machine: it reads the cache
(`handle_cache_and_async_logic`, `query_runner.py:1891`), decides staleness, dispatches async
(`enqueue_async_calculation`, `:1836`), executes and writes back
(`_execute_and_cache_blocking`, `:2370`). `query_runner.py` is 3188 lines and the runner base class
is two jobs welded together: how to build and execute _this_ query, and the caching and async
policy for _every_ query.

That matters because `run()` is the real chokepoint. Everything reaches it:

- `process_query_model` (`posthog/api/services/query.py:373`), which serves `POST /query/`, the
  endpoints product, the data catalog, notebooks, warming, exports, alerts and pulse;
- and roughly a dozen callers that skip the service layer entirely and call
  `runner.run(execution_mode=...)` themselves — `posthog/temporal/experiments/activities.py:211`
  and `:517`, `posthog/api/event.py:483`, `posthog/api/person.py:1057`,
  `posthog/api/web_vitals.py:88`, `posthog/hogql_queries/utils/time_sliced_query.py:81` (up to
  four blocking runs in one request), and others.

55 non-test files reference `ExecutionMode`. Any plan that adds a layer _above_
`process_query_dict` reaches neither group, cannot delete the enum, and ends up as a second
orchestration layer beside the one it was meant to replace.

So v2 is not a new path beside the old one. **It is extracting the state machine out of
`QueryRunner` into its own package, and leaving `run()` as a shim.**

### Nine inputs decide freshness and waiting

`ExecutionMode` looks like the decision. It is one of nine inputs:

1. **The surface default** — `SURFACE_DEFAULT_EXECUTION_MODE[surface]` (`refresh_policy.py`), when
   the client sends no `refresh` param.
2. **An explicit `?refresh=`**, which overrides it.
3. **`request_data.async_`**, a legacy body field overriding it again (`query.py:154-155`).
4. **The query endpoint's rewrite**: `CACHE_ONLY_NEVER_CALCULATE` becomes
   `RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE` (`query.py:157-159`).
5. **Two more rewrites of the same input to a _different_ mode**, on the values endpoints:
   `posthog/api/person.py:1050-1051` and `posthog/api/event.py:478-479` turn it into
   `RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS`.
6. **The shared clamp**, `shared_insights_execution_mode` (`query_runner.py:349-365`), which for
   `force_blocking` substitutes a staleness window instead of a mode.
7. **`cache_age_seconds`**, a per-request staleness override threaded separately into the runner.
8. **`requires_fresh_calculation()`** (`query_runner.py:2140-2147`), letting a runner force
   blocking whatever was asked.
9. **The frontend's rewrite**, below, plus **`acceptStaleCache`**, a separate `performQuery`
   argument expressing "serve stale" for callers whose mode cannot.

Three of these silently override the caller, in three different layers, two of them to different
values than each other.

### Async is smaller and more scattered than it looks

```ts
// frontend/src/queries/nodes/DataNode/dataNodeLogic.ts:980-982
if (!pollOnly && ['async', 'force_async'].includes(refresh)) {
  refresh = refresh.startsWith('force_') ? 'force_blocking' : 'blocking'
}
```

Every load through `dataNodeLogic` asks for async and is rewritten to blocking. Async survives in
three places, none of them the common insight path:

1. **Attaching to an in-flight run** (`dataNodeLogic.ts:904-910`), which sets `pollOnly`.
2. **Dashboard tiles**, which do not use `performQuery` at all. `getInsightWithRetry`
   (`dashboardUtils.ts:275`) calls `GET api/environments/{team}/insights/{id}/?refresh=blocking`,
   retries five times on rate-limit, then falls back to `refresh=force_async` on the same
   endpoint and polls `GET /query/{id}/` (`:302-338`), called from `dashboardLogic.tsx:3977`
   and `:4091`.
3. **Experiments**, via `getExperimentRefreshMode` (`metricQueryUtils.ts:605-613`) — which is
   itself being migrated to blocking behind `EXPERIMENTS_SYNC_QUERIES`, with a comment saying to
   delete the async branch once the flag is at 100%.

So the async machinery carries a large share of the complexity for a shrinking set of consumers,
and the one surface that will still need it after the experiments flag lands is dashboard tiles,
through an endpoint the frontend flag would never have reached.

### Four identities, and one of them is user-blind

1. The **cache key**: query, team, modifiers, timezone, week start, **and access restrictions**
   (`get_cache_payload`, `query_runner.py:2597`; access partitioning at `:3020-3053`).
2. The **client query ID**: whatever the caller sent, else a uuid7. For insight runs it is set to
   the cache key — `query_id=self.query_id or cache_manager.cache_key`, "Use cache key as query ID
   to avoid duplicates" (`query_runner.py:1872`).
3. The **running-queries hash**, `running_queries:{team}`, cache key to query ID.
4. The **coalescer key**: `sha256(team_id:method:path:normalized_body)`, with only
   `client_query_id` and `session_id` stripped (`query_coalescer.py:377-397`).

The fourth carries **no user identity**. `QueryCoalescingMixin.dispatch` does run `initial()` —
auth, permissions, throttling — before serving a follower (`:408-440`), so a follower is
authenticated and passes the viewset's checks. What it does not check is the per-query access
partitioning that the _cache_ key encodes. Two users on one team with different property or
object-level restrictions, posting the same body, share one computed result.

That is the strongest argument for a single identity, and it is an argument the previous draft of
this document missed entirely.

### The status record is a result store and a routing table

`GET /query/{id}/` answers from a Redis record holding the full result, so it cannot expire while
a client might poll and cannot be kept long because it holds a copy. #94496, #94595 and #94537 all
foundered on that.

It has also grown non-status jobs: `retrieve` reads `query_status.labels` to find a
managed-warehouse connection and check its readiness before answering (`query.py:405-425`), with
the label written by a runner (`hogql_query_runner.py:121-127`).

### There is prior art in-tree

`posthog/hogql_queries/refresh_policy.py` is the per-surface policy idea, stopped halfway — a
deliberate refactor at this problem (Paul D'Ambra, #72536, 22 July 2026). Its docstring:

> Historically each surface's _default_ ... was an accident of which query params its client
> happened to send, invisible at the route. This module makes that default explicit and
> per-surface, in one table.

Nine `ComputeSurface` values are wired into insights, dashboards and sharing, and every entry in
the table is `CACHE_ONLY_NEVER_CALCULATE` — deliberately, to reproduce historical behavior, so a
surface can be changed one greppable line at a time.

`products/alerts/backend/evaluation/contract.py:97-101` has the same shape by accident, arriving
with a feature (Vasco de Krijger, #62988, 25 June 2026).

The direction is accepted in-tree. v2 extends `ComputeSurface` rather than inventing a vocabulary
beside it.

## Part 2: the model

### Name the axes

- **`max_age`** — the freshness requirement, and **not a number**. `is_stale`
  (`posthog/caching/utils.py:69-97`) returns false outright when the query's `date_to` predates
  the last refresh, and otherwise derives the threshold from the query's interval, so a monthly
  trend stays fresh far longer than a minute-interval one. Three modes exist:
  `ThresholdMode.DEFAULT`, `LAZY`, `AI`. So the type is `ThresholdMode | explicit seconds` — the
  runner's own policy, or an override replacing it, which is what `_cache_age_override` already
  does (`query_runner.py:2840-2854`).
- **`stale_while_revalidate`** — how much older a result may be and still be served, with a
  refresh started behind it. Subsumes `lazy_async`, `async_except_on_cache_miss` and
  `acceptStaleCache`.
- **`wait`** — how long the caller holds the request. `0` returns immediately. The only thing
  separating blocking from async.
- **`compute`** — may this request start work. The cache-only callers are real: insight AI
  analysis and suggestions both use `CACHE_ONLY_NEVER_CALCULATE` deliberately
  (`products/product_analytics/backend/presentation/insight.py:2282, 2327`).

One rule replaces the branch tree:

> Serve the cached result if it satisfies `max_age`. Otherwise, if it satisfies
> `stale_while_revalidate`, serve it and refresh behind it. Otherwise start or join a run, wait up
> to `wait`, and return what exists plus the run's state if the wait expires.

`cache_age_seconds` stops being a separate channel — it _is_ an explicit `max_age`.
`requires_fresh_calculation` becomes a runner declaring `max_age = 0` rather than rewriting a mode.
The three silent rewrites disappear, because a surface preset already states what that surface
does.

`SURFACE_DEFAULT_EXECUTION_MODE` becomes `SURFACE_POLICY`: the same table, in the same file, four
values per row instead of one, each with its reason.

### One identity

A run is identified by a fingerprint derived server-side from the query under the caller's own
identity — the cache key, which already partitions by access restrictions.

That collapses the four identity schemes into one, and closes the coalescer's user-blind sharing
described above. It also means a poll cannot fail because a record expired: nothing polls a
record, the question is simply asked again.

### Polling is asking again

No status endpoint in the steady state. A client re-issues the same request with `wait: 0` and
gets the result or the run's state. Cancellation is the same request with `cancel: true`.

The client sends the query, never a fingerprint. That is a security property: the poll endpoint
authorizes on team membership alone today, and since insight query IDs _are_ cache keys, a
restricted user can already poll an unrestricted colleague's key. Deriving the fingerprint
server-side means a client can only address a result it could have computed itself.

Two callers do not fit and need work rather than assertion:

- **The notebook data plane** (`sql_v2_data_plane.py:248-290`) is authenticated by a data-plane
  token with no user, but enqueues with `user_id=user.id` (`:213`). A `wait: 0` re-issue by the
  kernel would derive the fingerprint under a userless principal and miss the run it is trying to
  reach. It also returns Arrow bytes or a 302 to presigned S3, not a query response.
- **Notebook direct runs** (`sql_v2_direct.py:211-225`) identify by run row on purpose —
  `refresh_requested=True`, "A Run click always executes" — so a fingerprint would collapse two
  clicks of identical SQL, which is the opposite of what that path wants. It also reads
  `pickup_time`/`end_time` off the record for timings (`:238-252`) and keeps serving results from
  it for client-side paging.

Both need a per-run identity that the query alone cannot supply. That is a real carve-out, not a
detail.

### What the run record holds

State, timings, the Celery task id for cancellation, progress, terminal error. The timings stay
because notebooks reads them. Results and product routing leave: the managed-warehouse readiness
check moves to the runner that owns the label.

### Queries that cannot be async

`process_query_model` handles `HogQLAutocomplete`, `HogQLMetadata`, `DatabaseSchemaQuery` and
`HogQuery` before any runner exists (`posthog/api/services/query.py:299-360`). They have no cache
key, so they cannot be resolved by asking again, and `wait: 0` is invalid for them.

## Part 3: architecture

```text
posthog/query_execution/
  policy.py       max_age / swr / wait / compute; extends SURFACE_DEFAULT_EXECUTION_MODE
  fingerprint.py  the one identity: today's cache key, derivation unchanged
  runs.py         start-or-join, wait, progress, cancel; the single Redis record
  execute.py      the one rule; the only module that decides anything
```

`QueryRunner` keeps what is query-specific: `calculate`, `to_query`, `get_cache_key`,
`cache_target_age`, `_is_stale`, `requires_fresh_calculation`. It loses the state machine —
`handle_cache_and_async_logic`, `enqueue_async_calculation`, and the caching half of
`_execute_and_cache_blocking` move into `execute.py`.

`QueryRunner.run(execution_mode=...)` becomes a shim: map the mode to a policy, call
`execute.py`, return the same shape. **Every existing caller keeps working unchanged** — all 55
files, the insights endpoint, dashboard tiles, temporal activities, the values endpoints. The shim
is what gets deleted at the end.

Unchanged: `posthog/query_cache/`, the failure breaker, `posthog/clickhouse/client/limit.py`, the
Celery task, and the coalescer (see Risks).

## Part 4: rollout

**Phase 1 — extract.** Move the state machine into `query_execution/`, with `run()` as the shim.
No behavior change, nothing flagged. This is the bulk of the work and it is a refactor, reviewable
as one.

**Phase 2 — flag inside the shim, per team.** Not in `performQuery`. The frontend does not decide
backend orchestration, and a frontend flag would have missed dashboard tiles and every server-side
caller. Flagging in the shim covers every surface at once for a team. Internal teams first.

**Phase 3 — move callers onto policies** and off `ExecutionMode`, starting with the surfaces that
already have a policy table (insights, dashboards, sharing) and the products with a local preset
(alerts). This is cosmetic while the shim works, so it can proceed at whatever pace review allows.

**Phase 4 — delete** the shim, the enum, the running-queries hash, the status endpoint, `pollOnly`,
`acceptStaleCache`, `async_`, and the three rewrites. Not the coalescer.

No shadow phase comparing v2 to v1 and serving v1. Matching v1 exactly is not the goal — some of
what it does is what we are removing.

## Part 5: risks

- **Liveness has no mechanism today, and the obvious one does not cover insights.** Start-or-join
  needs to know whether a run is really alive. The heartbeat key looks like the answer: it is
  written at `execute_async.py:122` and _is_ read, by `is_ch_query_alive`
  (`computation_notifications.py:61-65`) for lazy computation. But it is only written from
  `update_clickhouse_query_progresses`, driven by `poll_query_performance`, which reconstructs a
  manager only for ids matching `(\d+)_(UUID)` (`poll_query_performance.py:19`) and filters
  ClickHouse on `initial_query_id REGEXP '\d+_[0-9a-f]{8}-'` (`:40,50`). Insight runs are filed
  under the cache key, `cache_{team}_{sha256hex}` (`posthog/utils.py:1322`) — no hyphen, not a
  UUID. So no heartbeat and no progress is written for exactly the population liveness needs.
  (It also means `showProgress=true`, which `pollForResults` always sends,
  `frontend/src/queries/query.ts:141`, returns nothing for insights.) Liveness must be designed,
  not inherited. This is the largest open problem.
- **Keep the coalescer.** It absorbs a herd of identical requests before the query is parsed and
  access controls preloaded. The fingerprint runs after auth and parsing and cannot be that cheap.
  Keep the middleware as the outer dedup and add the fingerprint as the inner one; fix its
  user-blind key by including the access-restriction component of the cache payload.
- **The fingerprint moves whenever `get_cache_payload` changes.** A new modifier or access-control
  field resets every run identity at once. Cache-key changes already cause recompute storms; this
  adds a dedup gap in the same window.
- **`wait` occupies a worker, and `ee/hogai` is the sharp case.** Its executor deliberately picks
  `thread_sensitive=execution_mode not in BLOCKING_EXECUTION_MODES`
  (`query_executor.py:371`) so async polling does not hold a thread, then polls Redis for up to
  five minutes. Replacing that with a long `wait` inverts the choice and holds a
  `database_sync_to_async` thread per AI query. Every surface preset needs a `wait` ceiling.
- **`stale_while_revalidate` already exists one layer down.** Web analytics implements RFC 5861 at
  the precompute layer with its own dedup key and budget
  (`web_lazy_precompute_common.py:152-320`), gated on the execution mode at `:234`. Two SWR
  windows at two layers with different keys needs a decision this document does not make.
- **The cache is not always seven days.** `retention_ttl` (`posthog/query_cache/cache.py:42-52`)
  returns 24 hours for entries with no insight or dashboard written through a programmatic access
  method, and entries are evicted before TTL under the team size limit
  (`size_tracker.py:35-37`). "A poll cannot fail because a record expired" is accurate; "the
  answer is always there" is not. An expired poll silently recomputes.
- **`calculate_for_query_based_insight` is a chokepoint** for insights, alerts, pulse and exports.
  The shim means its signature need not change until Phase 3.

## Not in scope

Query runners' own logic, HogQL, ClickHouse, the cache storage format and S3 tiering, the failure
breaker, concurrency and rate limits, the experiments recalculation workflow, and the two non-query
uses of `QueryStatusManager` (notebooks frame materialization, lazy computation) which should not
be on it at all.

## How this was checked

Verified by reading the code: the nine inputs and all three rewrites; the `dataNodeLogic` async
rewrite; the dashboard-tile path through the insights endpoint; direct `runner.run()` callers;
the four identity schemes and the coalescer's user-blind key; `is_stale`'s interval-awareness and
three threshold modes; the heartbeat's writer, reader, and the id-format gap; `refresh_policy.py`
and the alerts helper, including authorship; the notebooks direct and data-plane paths; the
non-runner query kinds; `retention_ttl`.

Not verified: whether shared and embedded dashboards ever poll from the browser. This document
previously asserted they do not. `dataNodeLogic.ts:988-996` loads whenever
`query_status.complete === false`, which is the state the `SHARED` clamp to
`EXTENDED_CACHE_CALCULATE_ASYNC_IF_STALE` produces, and the `pollOnly` docstring
(`frontend/src/queries/query.ts:176-178`) asserts the opposite. Treat it as open.

Also not verified: the current rollout percentage of `EXPERIMENTS_SYNC_QUERIES`, which decides
whether experiments is still an async consumer by the time Phase 2 lands.
