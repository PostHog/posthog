# Problem

Every error thrown is an exception. Our error tracking groups exceptions into issues.

An exception is an event in PostHog.
An issue is an entity in our Postgres database.

When querying for the issues list, we have to query two data sources:

- Postgres for issue-related things (name, description, status, assignee),
- ClickHouse for everything else (occurrences, affected users, charts, etc.).

In general, this is suboptimal.

To make things worse, we allow filtering by issue-specific properties.
So when we query for, say, the 10 ACTIVE issues with the most occurrences, we:

- go to ClickHouse and "construct" these 10 issues,
- then check Postgres and find that 1 of these 10 issues does not have ACTIVE status,
- drop it,
- display 9 issues even though we should display 10.

# Plan

We want to store copies of issues in ClickHouse and keep them in sync,
so we only have to query a single data source (faster and fewer problems with filtering).

1. Create a table in ClickHouse

First, we need to create a table. The engine should be a ReplacingMergeTree.

We want to use `updated_at` as the version.

ClickHouse will automatically deduplicate old versions thanks to that engine.

2. Live updates

Any time a new issue is created or updated, we write to the ClickHouse table (via a Kafka topic).

We could use signals:

```python
@receiver(post_save, sender=ErrorTrackingAutoCaptureControls)
```

These run on every instance, though, so we should add something in between — like a Celery task with deduplication, or another approach.

3. Backfill

After we confirm that live updates are working, we need to run a backfill to migrate all existing issue data into the ClickHouse table.

4. Rewrite queries

We would then rewrite queries to use pure ClickHouse.

# Questions for the ClickHouse team

- What is the delay between emitting something to the Kafka queue and having it available in ClickHouse reads? We want to avoid situations where a user changes an issue's status, goes back to the listing page, and the old status is still showing because the change hasn't propagated yet. Something sub-1s would be ideal.
