## Creating ClickHouse schema changes

**Important:** ClickHouse schema changes should be created as a separate PR from application code changes. This allows for:

- Independent review and testing of schema migrations
- Safer rollout of database changes
- Clear separation between infrastructure and application logic changes

## About migrations

Not all migrations are intended to run on all nodes every time, because of the topologies we run. Some nodes are intended to only perform compute operations and do not contain sharded tables.

Some tables are meant to run only on a couple of nodes, like some Kafka tables, to prevent the whole cluster to run too many insertions in ClickHouse.

And, in some other cases, we want to only create one table (like a unique Kafka consumer) in one node.

Because of the above, take the following advice into consideration when manipulating schemas for ClickHouse.

### When to run a migration ONLY on a data node

- When adding / updating a sharded data table

In the above cases, create a migration and call the `run_sql_with_exceptions` function with the `node_roles` set to `[NodeRole.DATA]`.

<details>

<summary>Example</summary>
For example, the `sharded_events` table is a sharded table. Thus, it should only be added on data nodes.

Also, since to fill this table we need to consume events from Kafka, we need to run Kafka consumers on the data nodes, which would include the materialized view and the writable distributed table. So the `kafka_events_json`, `events_json_mv` and `writable_events` tables should also be added on them.

</details>

### When to run a migration for DATA and COORDINATOR nodes

- Basically when the migration does not include any of the above listed in the previous section.
- When adding / updating a distributed table for reading
- When adding / updating a replicated table
- When adding / updating a view
- When adding / updating a dictionary
- And so on

In the above cases, create a migration and call the `run_sql_with_exceptions` function with the `node_roles` set to `[NodeRole.DATA, NodeRole.COORDINATOR]`.

<details>

<summary>Example</summary>

Following the previous section example, the sharded events table along with the Kafka tables, materialized views and writable distributed table would be added to the data nodes. However, the `distributed_events`, which is the table used for the read path, would be added to all nodes.

</details>

## When to use NodeRole.INGESTION_SMALL or NodeRole.INGESTION_MEDIUM

We have extra nodes with a sole purpose of ingesting the data from Kafka topics into ClickHouse tables. These nodes don't contain any data perse, only Kafka tables and Distributed ones, along with the materialized views that connect them.

Use these node roles exclusively when you need to ingest data from Kafka into ClickHouse.

When you want to pull data from Kafka into ClickHouse, you should:

1. Create a Kafka table.
2. Create a writable table only on ingestion nodes. It should be a Distributed table with your data table.
    1. If your data table is non-sharded, you should point it to one shard: `Distributed(..., cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)`, without using any sharding key.
    2. If your data table is sharded, you should point it to all shards: `Distributed(..., cluster=settings.CLICKHOUSE_CLUSTER, sharding_key="...")`, using a sharding key.
3. Create a materialized view between Kafka table and the writable table.

Example PR for non-sharded table: https://github.com/PostHog/posthog/pull/38890/files
Example PR for sharded table: https://github.com/PostHog/posthog/issues/38668/files

`Medium` tier contains 4 consumers, while `Small` tier contain just one. Depending on the throughput of the Kafka topic, you should choose the appropriate tier, in case of doubts choose `Small` and you can later upgrade to `Medium` if lag is too high.

## When to use NodeRole.ALL

We are introducing changes to our ClickHouse topology frequently, introducing new types of nodes.

Rarely, you'll need to run a migration on all nodes. In that case, you can use the `NodeRole.ALL` role. You should only use it when you're sure that the change is safe to apply to all nodes.

In the vast majority of cases, just follow the [previous](#when-to-run-a-migration-only-on-a-data-node) [sections](#when-to-run-a-migration-for-data-and-coordinator-nodes).

### The ON CLUSTER clause

**Do not use the `ON CLUSTER` clause**, since the DDL statement will be run on all nodes anyway through the `run_sql_with_exceptions` function, and, by default, the `ON CLUSTER` clause makes the DDL statement run on nodes specified for the default cluster, and that does not include the coordinator.
This may cause lots of troubles and block migrations.

The `ON CLUSTER` clause is used to specify the cluster to run the DDL statement on. By default, the `posthog` cluster is used. That cluster only includes the data nodes.

### Testing

To re-run a migration, you'll need to delete the entry from the `infi_clickhouse_orm_migrations` table.

## Ingestion layer

We have extra nodes with a sole purpose of ingesting the data from Kafka topics into ClickHouse tables. The way to do that is to:

1. Create your data table in ClickHouse main cluster.
2. Create a writable table only on ingestion nodes: `node_roles=[NodeRole.INGESTION_SMALL]`. It should be Distributed table with your data table. If your data table is non-sharded, you should point it to one shard: `Distributed(..., cluster=settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)`.
3. Create a Kafka table in ingestion nodes: `node_roles=[NodeRole.INGESTION_SMALL]`.
4. Create materialized view between Kafka table and writable table on ingestion nodes.

Example PR for non-sharded table: https://github.com/PostHog/posthog/pull/38890/files

**How and why?**

Our main cluster (`posthog`) nodes were overwhelmed with ingestion and sometimes the query load
was interfering with ingestion. This was causing delays and at the end incidents.

We added new nodes that are not part of our regular cluster setup, we run them on Kubernetes.

ClickHouse cluster as defined in it is a logical concept and one may add nodes that are running in different places, this is how we created a new cluster that has all workers, coordinator and our new ingestion nodes.
