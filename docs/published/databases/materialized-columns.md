---
title: Working with ClickHouse materialized columns
sidebar: Handbook
showTitle: true
---

This document outlines what materialized columns in ClickHouse are, how we're making use of them and how to manage them on cloud.

## Background

We currently store JSON data in string columns in clickhouse, reading and parsing that data at query-time. This can be slow due to how "fat" these columns are.

Materialized columns allow us to "store" specific properties stored in JSON as separate columns that are there on disk, making reading these columns up to 25x faster than normal properties.

Also check out our [ClickHouse manual](/handbook/engineering/clickhouse/working-with-json) and [blog post](/blog/clickhouse-materialized-columns) for more information.

## Materialized columns in practice

Materialized columns play a huge role in optimizing performance for large clients having difficulties with performance.

This is why we automatically materialize columns and have tooling for creating them manually as well.

Note that materialized columns also require backfilling the materialized columns to be effective - an operation best done on a weekend due to extra load it adds to the cluster.

### Automatic materialization

We have a cron-job which analyzes slow queries ran last week and tries to find properties that are used in these slow queries, materializing some of these. Code for this can be found in `ee/clickhouse/materialized_columns/analyze.py`

Note that this cron can often be disabled due to cluster issues or ongoing data migrations.

See [environment variables documentation](/docs/self-host/configure/environment-variables) + instance settings for toggles which control this.

### Manual materialization

`python manage.py materialize_columns` command can be used to manually materialize one or more properties.

Alternatively this can be done over `python manage.py shell_plus`. One example of materializing all properties used by a team can be found here:

```python
from ee.clickhouse.materialized_columns.columns import *

pd = PropertyDefinition.objects.filter(team_id=2635)
used_props = set(p.name for p in pd if "distinct_id" not in p.name and "$" not in p.name)

event_props_to_materialize = used_props - set(get_materialized_columns("events", use_cache=False))

from ee.clickhouse.sql.person import GET_PERSON_PROPERTIES_COUNT
rows = sync_execute(GET_PERSON_PROPERTIES_COUNT, {"team_id": 2635})
person_props_to_materialize = set(name for name, _ in rows if "$" not in name) - set(get_materialized_columns("person", use_cache=False))


from ee.clickhouse.materialized_columns.analyze import logger, materialize_properties_task

columns_to_materialize = []
columns_to_materialize += [("events", prop, 0) for prop in event_props_to_materialize]
columns_to_materialize += [("person", prop, 0) for prop in person_props_to_materialize]

materialize_properties_task(
    columns_to_materialize=columns_to_materialize,
    backfill_period_days=90,
    dry_run=False,
    maximum=len(columns_to_materialize)
)
```

Note that this snippet might need modification depending on the usecase.
