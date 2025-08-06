## About migrations

Not all migrations are intended to run on all nodes every time, because of the topologies we run. Some nodes are intended to only perform compute operations and do not contain sharded tables.

Some tables are meant to run only on a couple of nodes, like some Kafka tables, to prevent the whole cluster to run too many insertions in ClickHouse.

And, in some other cases, we want to only create one table (like a unique Kafka consumer) in one node.

Because of the above, take the following advice into consideration when manipulating schemas for ClickHouse.

### When to run a migration ONLY on a data node

- When adding / updating a Kafka table
- When adding / updating a materialized view
- When adding / updating a sharded table
- When adding / updating a distributed table used for the write path

In the above cases, create a migration and call the `run_sql_with_exceptions` function with the `node_role` set to `NodeRole.DATA`.

<details>

<summary>Example</summary>
For example, the `sharded_events` table is a sharded table. Thus, it should only be added on data nodes.

Also, since to fill this table we need to consume events from Kafka, we need to run Kafka consumers on the data nodes, which would include the materialized view and the writable distributed table. So the `kafka_events_json`, `events_json_mv` and `writable_events` tables should also be added on them.

</details>

### When to run a migration for all nodes

- Basically when the migration does not include any of the above listed in the previous section.
- When adding / updating a distributed table for reading
- When adding / updating a replicated table
- When adding / updating a view
- When adding / updating a dictionary
- And so on

In the above cases, create a migration and call the `run_sql_with_exceptions` function with the `node_role` set to `NodeRole.ALL`.

<details>

<summary>Example</summary>

Following the previous section example, the sharded events table along with the Kafka tables, materialized views and writable distributed table would be added to the data nodes. However, the `distributed_events`, which is the table used for the read path, would be added to all nodes.

</details>

### The ON CLUSTER clause

The ON CLUSTER clause is used to specify the cluster to run the DDL statement on. By default, the `posthog` cluster is used. That cluster only includes the data nodes.

Ideally, **do not use the ON CLUSTER clause**, since the DDL statement will be run on all nodes anyway through the `run_sql_with_exceptions` function, and, by default, the ON CLUSTER clause make the DDL statement run on nodes specified for the default cluster, and that does not include the coordinator.

### Testing

To re-run a migration, you'll need to delete the entry from the `infi_clickhouse_orm_migrations` table.
