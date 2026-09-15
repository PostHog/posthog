# Data modeling demand tracking

Consumer queries executed through `HogQLQueryExecutor.execute()` buffer the latest demand timestamp for each referenced saved query in Redis.
Resolution preserves saved-query identity for both ordinary and materialized views.
Repeated references within a query collapse into one timestamp.
Recording happens after preparation and before execution, so failed execution attempts count but SQL generation and validation do not.
Queries tagged as data modeling, schema introspection, enrichment, or cache warmup do not count.
Model refreshes use a separate execution path and do not record demand.

Every five minutes, `flush_model_demand` reads up to 1,000 pending saved queries from each of 16 Redis shards.
For each team, it maps saved queries to all their DAG nodes and propagates demand through upstream dependencies, including source tables and dependencies behind materialized views.
Managed cross-DAG reference nodes propagate to the referenced saved query's nodes too.
The worker uses the graph at flush time; a dependency edited between execution and persistence can receive approximate attribution.

`Node.last_demand_at` stores the newest observed consumer demand, directly or through a descendant.
Database updates never move this timestamp backward.
The worker acknowledges a team's Redis entries only after that team persists, and only if no newer demand has replaced them.
Retries can repeat writes safely; failed flushes leave entries pending.
A team that fails to persist does not hold back the other teams or the later shards.
The worker reports the first failure after it reads every shard, so monitoring still detects it.
Buffer failures do not fail consumer queries, but Redis data loss can lose unflushed observations.

## Coverage

This tracks executions, not cache hits.
Raw SQL, SQL compiled for execution outside `HogQLQueryExecutor.execute()`, and saved queries without DAG nodes are not covered.
Propagation relies on the stored dependency graph; missing or degraded edges leave gaps.
A null timestamp means no demand has been observed by this tracker, not proof that the model is unused.
The tracking start time and any outages must be considered when interpreting inactivity.

This tracking does not change refresh schedules or suspend models.
Cache-hit tracking is deferred to stage 2.
