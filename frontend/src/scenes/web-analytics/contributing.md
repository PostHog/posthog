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

## HogQL query examples and testing

For comprehensive documentation on how web analytics queries work, see [hogql_queries.md](./docs/hogql_queries.md). This guide covers:

- How to view generated HogQL queries via snapshot tests
- Testing queries directly using the PostHog API
- Query structure patterns for all web analytics query types (overview, trends, breakdowns)
- All breakdown types with their corresponding HogQL fields
- Event vs session property usage patterns
- Period comparison and bounce rate calculation details
- Tips for modifying and customizing queries

The snapshot tests in `posthog/hogql_queries/web_analytics/test/test_sample_web_analytics_queries.py` serve as the source of truth for query generation and are automatically kept up to date

## Sessions table

The sessions table is a core component of web analytics, you can check what defines a session on our doc and update it if it ever changes on the [website doc](https://posthog.com/docs/data/sessions). While we refer to it as "the sessions table", it's actually implemented as a set of ClickHouse tables that work together.

### How it works

The sessions table uses ClickHouse's `AggregatingMergeTree` engine to continuously aggregate events by session ID:

- Events are aggregated via materialized views that run automatically as events are inserted
- All events with the same session ID are merged using the sorting key on the version, you can check the current sorting key in the table definition in [sessions_v3.py](../../../../posthog/models/raw_sessions/sessions_v3.py)

### What gets aggregated

The sessions table stores pre-computed session properties essential for web analytics:

- Session timestamps (start, end)
- Entry and exit URLs, all URLs visited
- Device information (browser, OS, device type, viewport)
- Geographic data (country, region, city, timezone)
- Attribution data (UTM parameters, referring domain, ad IDs like gclid, fbclid, and 15+ other ad networks)
- Channel type (computed from attribution data)
- Event counts (pageviews, screens, autocapture events)
- Bounce detection (using efficient `uniqUpTo` aggregation)
- Feature flag values seen during the session
- Session replay presence

### Why session properties are central to web analytics

Session properties enable fast, attribution-focused analysis:

- **Attribution analysis**: Entry UTM parameters, referring domain, and channel type are session-level properties
- **Behavioral analysis**: Entry/exit pages, bounce rate, and page counts are naturally session-scoped
- **Anonymous-friendly**: Works immediately for anonymous users without person identification

### Sessions definition

Sessions follow the [PostHog session definition](https://posthog.com/docs/data/sessions): a session groups events with the same session ID, which is automatically managed by PostHog client libraries based on inactivity timeouts and session resets.

### Event capture in posthog-js

Understanding how posthog-js captures sessions and pageviews is essential for working with web analytics data.

#### Session handling

**Session lifecycle:**

- Session IDs generated using UUIDv7 format (time-ordered)
- Default 30-minute idle timeout (configurable via `session_idle_timeout_seconds`: 1min-10hrs)
- Maximum session length: 24 hours regardless of activity
- New sessions created when: no existing session, idle timeout exceeded, or max length exceeded
- Storage: Session data in cookies/localStorage as `[lastActivityTimestamp, sessionId, sessionStartTimestamp]`
- Each browser tab gets unique `windowId` (persists across reloads, new ID on duplication)

**Session attribution properties:**

Captured at session start and persisted for the session lifetime:

- Entry URL, referring domain, UTM parameters, initial pathname
- Become `$session_entry_*` properties on events (e.g., `$session_entry_url`)
- Aggregated into the sessions table for fast attribution analysis

#### Pageview tracking

**Automatic vs SPA tracking:**

- Traditional sites: `$pageview` events captured automatically on page load
- SPAs: Use `capture_pageview: 'history_change'` or `defaults: '2025-05-24'` to track navigation via History API
- Manual option: Call `posthog.capture('$pageview')` when needed

**Pageview properties:**

- `$pageview_id`: Unique identifier for current view
- `$prev_pageview_id`, `$prev_pageview_pathname`, `$prev_pageview_duration`: Previous page context
- Scroll metrics: `$prev_pageview_max_scroll`, `$prev_pageview_max_scroll_percentage`
- Content metrics: `$prev_pageview_max_content`, `$prev_pageview_max_content_percentage`

#### Key resources

- Session docs: <https://posthog.com/docs/data/sessions>
- Web analytics FAQ: <https://posthog.com/docs/web-analytics/faq>
- SPA pageview tutorial: <https://posthog.com/tutorials/single-page-app-pageviews>
- Source code: [session-props.ts](https://github.com/PostHog/posthog-js/blob/main/packages/browser/src/session-props.ts), [sessionid.ts](https://github.com/PostHog/posthog-js/blob/main/packages/browser/src/sessionid.ts), [page-view.ts](https://github.com/PostHog/posthog-js/blob/main/packages/browser/src/page-view.ts)

### Implementation details

The table definitions and materialized view logic are in:

- [posthog/models/raw_sessions/sessions_v3.py](../../../../posthog/models/raw_sessions/sessions_v3.py) - SQL table definitions and materialized view queries
- [posthog/hogql/database/schema/sessions_v3.py](../../../../posthog/hogql/database/schema/sessions_v3.py) - HogQL schema that exposes sessions table to queries
- [posthog/clickhouse/migrations/](../../../../posthog/clickhouse/migrations/) - Search for `sessions_v3` to find related migrations

## What is HogQL?

Web analytics queries are written in HogQL (sometimes referred to as Hog SQL or PostHog SQL). Here's some links to learn more about it:

- <https://posthog.com/blog/introducing-hogql>
- <https://posthog.com/handbook/engineering/databases/hogql-python>

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
