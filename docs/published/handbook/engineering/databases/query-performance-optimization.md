---
title: Query performance optimization
sidebar: Handbook
showTitle: true
---

Making sure PostHog operates fast at scale is key to our success.

This document outlines some best practices to achieve good query performance at scale, as well as describing tools and procedures to discover and fix performance issues.

PostHog uses two different datastores:

- **PostgreSQL**: row-oriented OLTP database, mainly used to store and query datasets using predictable clause(s). It is likely your best choice if:
  - the query pattern to access your dataset is predictable
  - the dataset will likely not grow overtime above (<= 1 TB)
  - the dataset needs to mutate often (`DELETE`/`UPDATE`)
  - the query pattern requires joins across multiple tables

- **ClickHouse**: column-oriented OLAP database, used to store large datasets and run on them analytical queries. It is likely your best choice if:
  - the query pattern to access your dataset is unpredictable
  - the dataset will likely grow overtime (> 1 TB)
  - the dataset doesn't need to mutate often (`DELETE`/`UPDATE`)
  - the query pattern doesn't requires joins across multiple tables

## PostgreSQL

#### Coding best practices

1. only ask for the field(s) you need: `SELECT name, surname` is better than `SELECT *` (the latter is only helpful in few edge cases)

1. only ask for the row(s) you need: use a `LIMIT` condition at the end of your query

1. (if possible) avoid explicit transactions: if you can't, keep them small since transactions lock the processing tables data and may result in deadlocks (super discouraged to use them in application hot paths)

1. (if possible) avoid `JOIN`

1. avoid the use of subqueries: a subquery is a `SELECT` statement that is embedded in a clause of another SQL statement. It's easier to write, but `JOIN`s are usually better-optimized for the database engines.

1. use appropriate [data type(s)](https://www.postgresql.org/docs/10/datatype.html): not all the types occupy the same, and when we use a concrete data type, we can also limit its size according to what we store. For example, `VARCHAR(4000)` is not the same as `VARCHAR(40)`. We always have to adjust to what we will store in our fields not to occupy unnecessary space in our database (and we should enforce this limit in the application code to avoid query errors).

1. use the `LIKE` operator only if necessary: if you know what you are looking for use the `=` operator

Note: for the Django app we currently rely on the Django-ORM as interface between our data and the relational database. While we don't directly write SQL queries in this case, the following best practices should be considered anyway.

If you want to print executed queries (while running with `DEBUG`) you can run:

```python
from django.db import connection
print(connection.queries)
```

while for an individual query you can run:

```python
print(Model.objects.filter(name='test').query)
```

#### Indexing

If you are programmatically ordering, sorting, or grouping by a column, you should probably have an index on it. The caveat is that indexing slows down writes to the table and takes disk space (please drop unused indexes).

Composite indices are useful when you want to optimize querying on multiple non-conditional columns. For more info on indices and multi-column indices see the [official docs](https://www.postgresql.org/docs/).

### How-to find slow queries

To find and debug slow queries in production you have a few options available:

- Browse to the [Diagnose](https://data.heroku.com/datastores/56166304-6297-4dce-af64-a1536ea2197c#diagnose) tab in Heroku Data's dashboard. You can break queries down by:
  - Most time consuming
  - Most frequently invoked
  - Slowest execution time
  - Slowest I/O
- You can also use Heroku's [Diagnose](https://blog.heroku.com/pg-diagnose) feature by running `heroku pg:diagnose` to get a breakdown of long running queries, long transactions, among other diagnostics.
- For a more raw approach you can access real time logs from Heroku by executing `heroku logs --app posthog --ps postgres`
- With any logs pulled from PostgreSQL you can use [pgbadger](https://github.com/darold/pgbadger) to find exactly the queries that are consuming the most time and resources.

### How-to fix slow queries

Fixing a slow query is usually a 3 steps process:

1. identify which part of the codebase is generating it (adding the stacktrace as query comments is usually helpful to map query <-> code).

1. re-run the query with `EXPLAIN (ANALYZE, COSTS, VERBOSE, BUFFERS, FORMAT JSON)` as prefix to get the query plan. Query plans aren't the easiest thing to read. They're packed with information and it's closer to being machine parsable than human readable. Postgres Explain Viewer 2 (aka [pev2](https://explain.dalibo.com/), see GitHub [repository](https://github.com/dalibo/pev2)) is a tool to simplify reading query plans. It provides a horizontal tree with each node representing a node in the query plan. It includes timing information, the error amount in the planned versus actual times, and badges for interesting nodes like "costliest" or "bad estimate".

1. fix the query that should now generate a less costly `EXPLAIN` plan.

### How-to reduce IO

1. Indices require IO, we can get rid of some IO by removing unused indices
2. Can check writes IO with something like:

```sql
SELECT total_time, blk_write_time, calls, query
FROM pg_stat_statements
ORDER BY (blk_write_time) DESC
LIMIT 10;
```

3. SELECTs can cause writes IO: https://blog.okmeter.io/postgresql-exploring-how-select-queries-can-produce-disk-writes-f36c8bee6b6f

#### Removing unused indices on foreign key fields

Say you have an index on `team_id`, `person_id`. If `team_id` and `person_id`
are Django foreign keys, it’s going to have created indices on `team_id` and
`person_id`. We can still use the composite index for both `team_id` and
`person_id` lookups, as mentioned on
https://www.postgresql.org/docs/11/indexes-multicolumn.html , thus we can avoid
having to write the other two indices by adding `db_index=False`

#### Removing foreign key fields

We don’t want to remove immediately as this is backwards incompatible. Do this as
a deprecation first. Let's get the gains of not having an index and constraint
first.

Rename e.g. `foreign_key_field` to `__deprecated_foreign_key_field`, add `db_column= foreign_key_field` such that attempts to reference from outside the model will require full qualification (we keep the field around such that Django doesn’t try to create deletion migrations)
Wait for one release of field deprecation to have been in place.
TODO: Somehow make select queries not request this field (i.e. to make it such
that we can drop the column).
Remove field completely in next release, add note that users should update through deprecation version such that running code is compatible

#### Finding and removing unused indices

How do you know if they are unused? Do something like

```sql
SELECT s.schemaname,
       s.relname AS tablename,
       s.indexrelname AS indexname,
       pg_relation_size(s.indexrelid) AS index_size
FROM pg_catalog.pg_stat_user_indexes s
   JOIN pg_catalog.pg_index i ON s.indexrelid = i.indexrelid
WHERE s.idx_scan = 0      -- has never been scanned
ORDER BY pg_relation_size(s.indexrelid) DESC;
```

If indices are unused, it should be safe to remove via removing `db_index=False`
and running `./manage.py makemigration`

This will generate a migration, however, if you look at the `./manage.py sqlmigrate`
output it may not be dropping the index concurrently, so will be a blocking
operation. To get around this we need to modify the migration:

1. use
   [`SeparateDatabaseAndState`](https://docs.djangoproject.com/en/3.2/ref/migration-operations/#separatedatabaseandstate)
   to allow django to keep track of the state of
   the model in the db, but let us modify how the index is created.
2. use
   [`RemoveIndexConcurrently`](https://docs.djangoproject.com/en/4.0/ref/contrib/postgres/operations/#django.contrib.postgres.operations.RemoveIndexConcurrently) to drop the index without blocking.

#### Avoiding locking on related tables

When e.g. bulk inserting, we can end up needing to select a lot of keys from
referenced tables. When we don't actually care about this, we can specify
`db_constraint=False`, along with making any required migrations if we're
updating an existing field.

## ClickHouse

#### How-to find slow queries

To find and debug slow queries in production you have several options available

##### Grafana

The [Clickhouse queries - by endpoint](https://metrics.posthog.com/d/vo7oCVZ7z/clickhouse-queries-by-endpoint) dashboard gives a breakdown of how things are looking reliability and performance-wise.
Highly used and slow/unreliable endpoints often indicate issues with queries.

##### PostHog `instance/status` dashboard

Under https://app.posthog.com/instance/status/internal_metrics you will find various metrics and query logs.
Note: if you are a staff user you can also analyze queries by clicking on them (or copying your own queries).

This analysis will output:

- Query runtime
- Number of rows read / Bytes read
- Memory used
- Flamegraphs for CPU, time and memory

These can be useful for figuring out _why_ certain queries are performing slow.

##### Metabase

Need more granular access to queries than these dashboards provide? Take a look at [this Metabase query](https://metabase.posthog.net/question/97). The ClickHouse `system` tables (e.g. `system.query_log`) provide a lot of useful information for identifying and diagnosing slow queries.

### How-to fix slow queries

See [ClickHouse manual](/handbook/engineering/clickhouse/) for tips and tricks.
