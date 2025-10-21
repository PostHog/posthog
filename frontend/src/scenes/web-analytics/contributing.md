# Web analytics

## How it works

- The starting point is the `WebAnalyticsScene` (a `Scene` is our unit of navigation in the front-end app) and the [<WebAnalyticsDashboard/>](./WebAnalyticsDashboard.tsx) which is the main UI component for the page
- This renders the `<Tiles/>` component, which grabs the list of tiles from Kea and maps over them
- The list of tiles is created in the [webAnalyticsLogic](./webAnalyticsLogic.tsx) selector called `tiles`, it's quite a large function, and it returns the data for every tile on the page. See also the `<WebAnalyticsTile/>` type
- Different types of tiles have different components to render them, I'll just focus on `<QueryTileItem/>` and `<TabsTileItem/>`. They call `<WebQuery/>`, which adds some UI for different kinds of queries, but they all eventually include a `<Query/>`
- The `<Query/>` component is the front-end component that handles everything related to actually running and visualizing one query, so it'll handle the network request, caching, rendering a table, etc.
- Jumping to the back end, when we make a query via the API it'll go through some django stuff, and then `get_query_runner` will try to find a query runner to run the specific query. One example is the [WebOverviewQueryRunner](../../../../posthog/hogql_queries/web_analytics/web_overview.py). These query runners have a `to_query` method which is responsible for generating SQL based on their inputs, and a `calculate` method which is responsible for running the query on clickhouse and returning a response.
- The query input and output types are defined in typescript, and we have a script which converts them to pydantic models for type hinting in the back end. See [schema-general.ts](../../queries/schema/schema-general.ts) and [schema.py](../../../../posthog/schema.py)

## How to regenerate the schema

In the project root

```bash
pnpm run schema:build
```

## What is HogQL?

Web analytics queries are written in HogQL (sometimes referred to as Hog SQL or PostHog SQL). Here's some links to learn more about it:

- https://posthog.com/blog/introducing-hogql
- https://posthog.com/handbook/engineering/databases/hogql-python

The TLDR is that you can construct HogQL queries by either parsing a string or by creating the ast nodes in python, and these are converted into Clickhouse SQL queries. There are lazy joins to make property access easier, so e.g. you can write `SELECT person.properties from events` instead of having to write the join between `events` and `persons` yourself, but the join will only be added to query if it's actually needed.

## Where do events come from?

Most web analytics users generate their events using [posthog-js](https://posthog.com/docs/libraries/js).

Note that web analytics and products analytics events are the same, the 2 products are different views over the same set of events. The biggest difference there is that web analytics is way more opinionated, and is especially designed to work well with [anonymous events](https://posthog.com/events), which are cheaper, and does this by heavy use of session properties instead of person properties.

## Toolbar

Some web analytics features are present in the [toolbar](https://posthog.com/docs/toolbar), for example the toolbar will show you web vitals for the page you are on.

## More resources

- Clickhouse
  - PostHog maintains a [Clickhouse manual](https://posthog.com/handbook/engineering/clickhouse)
  - Clickhouse has a [video course](https://learn.clickhouse.com/visitor_class_catalog/category/116050), which has been recommended by some team members
    - You can skip the videos that are about e.g. migrating from another tool to Clickhouse
  - [Designing Data-Intensive Applications](https://dataintensive.net/) is a great book about distributed systems, and chapter 3 introduces OLAP / columnar databases.
    - If you already know what an OLAP database is, you'd probably get more out of the Clickhouse course than this book. This book is good at introducing concepts but won't touch on Clickhouse specifically.
