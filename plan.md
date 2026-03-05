# Problem

Every error thrown is an exception. Our error tracking groups exceptions into issues.

Exception is an event in posthog.
Issue is an entity in our postgres.

When querying for issues list, we have to query two data sources:

- postgres for issues related things (name, description, status, assignee),
- clickhouse for all the other things (occurences, affected users, charts, etc...).

In general this is suboptimal.

But to make things worse -> we allow filtering by issue-specific properties.
So when we query for example 10 ACTIVE issues with the most number of occurences, we:

- go to clickhouse and "construct" these 10 issues,
- then we check postgres and see that 1 of these 10 issues does not have ACTIVE status,
- we then drop it,
- we display 9 issues even though we should display 10

# Plan

We want to store copies of issues in clickhouse and keep them in sync so we have to query only one data source (faster and less problems with filtering)

1. Create table in clickhouse

First step - we need to create a table. I think the engine should be a ReplacingMergeTree.

We want to use updated_as as the version.

As I understand it, that clickhouse table will get rid of old versions automatically thanks to that engine

2. Live updates

Any time new issue gets created or updated, we write to that clickhouse table (via kafka topic).

We could use signals

```python
@receiver(post_save, sender=ErrorTrackingAutoCaptureControls)
```

They run on every instance tho so we should add something in between like a celery task and dedup here or something else.

3. Backfill

After we confirm that live updates are working, we need to run backfill to migrate all existing issues data into that clickhouse table.

4. Rewrite queries

We would then rewrite queries to use pure clickhouse.

# Some questions to clickhouse team

- what is the delay between emiting something to kafka queue vs having it available in CH reads? We want to avoid situations where you change issue status, go back to the listing page and it's still there because that change is not yet available in CH. Something sub 1s would be perfect,
-
