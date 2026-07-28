# Persons on Events

## Background

We're getting ready to make a substantial change to the way [persons](https://posthog.com/docs/data/persons) and [events](https://posthog.com/docs/data/events) work by combining them and adding person IDs and properties onto events. This is the way we’ll be querying data for all teams using PostHog in the near future.

Why are we doing this? First, it makes queries significantly faster since we no longer have to join tables to get a result (JOINs are particularly expensive in ClickHouse); we can just look up everything in the events table instead. One query in our internal tests showed a 400x increase in speed, though 3-5x is the most common figure for speed improvements. This beta will help us understand this better in real-world conditions.

Secondly, feedback showed that users weren't able to create queries based on person properties at the time of an event. By putting person properties on events, this becomes the new default, while still enabling you to filter insights based on the latest properties using cohorts.

## Roll-out

We're currently offering the new query experience for Beta testers. As it is in Beta, you may or may not spot a few bugs here and there, please use the in-app bug reporting option and mention that you're a PoE (Persons on Events) beta tester.

Since this isn't fully ready yet we might offer you one of the roll-out stage options from below:

## None: JOIN-based queries

As reference here are the two aspects of queries that might change and how they work before PoE:

### 1. Filtering on person properties

Latest person properties are joined in during query time.

### 2. Insights counting unique persons

Distinct_id to Person mapping is joined together at query time, see [docs](https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons).

## PoEv1

### 1. Filtering on person properties

Person properties at the time the event was processed are used, see [docs](https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties)

### 2. Insights counting unique persons

Person IDs at the time the event was processed are used. Let's look at the same example from the [docs](https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons)

| ID  | Event       | `person_id` |
| --- | ----------- | ----------- |
| 1   | viewed page | `user1`     |
| 2   | viewed page | `user2`     |
| 3   | viewed page | `user1`     |

> **Note:** This isn't _exactly_ how `person_id`'s are stored within the events table, but it will help us to keep things simple.

In this case, if we ran a query asking for the number of unique users who viewed a page, we would get a result of `2`, as our table contains 2 unique `person_id`'s.

The way we write the `person_id` to each event has some implications for the number of unique users that are displayed:

1. Some users might be counted twice on the trend graph.
   The source of truth for data is the events table. Since this is point-in-time data, it is not possible to determine whether two `person_id`'s were later merged into a single user, which results in them being counted separately.
2. In the person modal, the count may be lower than the count displayed in the graph.
   Persons who've been merged into one have one of their old IDs deleted. We remove these people from the persons modal, as there's no place to link them to.
3. If a merge happens in the middle of a funnel, the user will show as having dropped off, instead of completed the funnel.

To understand better how these scenarios can arise, let's take a look at some specific examples.

| Day | Event    | distinct_id              | `person_id` |
| --- | -------- | ------------------------ | ----------- |
| 1   | other    | Alice                    | user-1      |
| 2   | pageview | anon-1                   | user-2      |
| 2   | identify | Alice (anon-id = anon-1) | user-1      |

In this case, we have a user Alice who sends an 'other' event on day `1` from her mobile phone.
On day 2, Alice decides to view the homepage from her desktop where she isn't logged in. This results in the pageview event being associated with a newly created Person (`user-2`).
She then logs in to her account, which sends an identify event that merges `user-2` into `user-1`.
This mean that we delete `user-2` from the persons table and all future events from `anon-1` will be tied to `user-1` (note that we never alter the events table to reflect this).

In this case, we’d show 1 unique user in the trend graph for pageviews, but since `user-2` was deleted during the merge, we would show 0 users in the person modal.

If we had a funnel that tracked `pageview` -> `identify`, Alice would show as having dropped off in that funnel (whereas without PoEv1 it would show as being completed).

To continue the example, let's say that Alice views the homepage again now that she is logged in.

| Day | Event    | distinct_id                       | `person_id` |
| --- | -------- | --------------------------------- | ----------- |
| 1   | other    | Alice                             | user-1      |
| 2   | pageview | anon-1                            | user-2      |
| 2   | identify | Alice (anon_distinct_id = anon-1) | user-1      |
| 2   | pageview | Alice                             | user-1      |

In this case, the trend graph would show 2 unique users (based on person_id = `user-1` and `user-2`) but the Person modal would only show `user-1` as `user-2` has been deleted.

## PoEv2

aka PoE with future merges

### 1. Filtering on person properties

Person properties at the time the event was processed are used, see [docs](https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties)

### 2. Insights counting unique persons

- All [person merges](https://posthog.com/docs/how-posthog-works/ingestion-pipeline#merging-two-persons) that were done before enabling will be counted separately (see PoEv1 above).
- All merges going forward will update the events table, i.e. unique user counts work the same way as with JOINs, see [docs](https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons).

> **Note:** We don't _exactly_ update the events table directly during event processing, but it's rather a simplification we're using here to keep the docs easy to follow.

## PoEv3

aka PoE with future merges and data backfill

### 1. Filtering on person properties

Person properties at the time the event was processed are used, see [docs](https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties)

### 2. Insights counting unique persons

Same as JOIN based queries, see [docs](https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons).
