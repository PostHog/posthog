# Joining citations to Google Search Console

Search Console data reaches PostHog through a `GoogleSearchConsole` data warehouse source.
Once synced, its tables are plain HogQL tables and join to `system.aeo_citation_checks` and
to `sessions` like any other.

## Contents

- [Find the tables](#find-the-tables)
- [Tables and columns](#tables-and-columns)
- [Recipe: how do our cited pages rank on Google?](#recipe-how-do-our-cited-pages-rank-on-google)
- [Recipe: do engine searches match the queries we rank for?](#recipe-do-engine-searches-match-the-queries-we-rank-for)
- [Recipe: topic scorecard](#recipe-topic-scorecard)
- [What this join cannot tell you](#what-this-join-cannot-tell-you)

## Find the tables

1. `posthog:external-data-sources-list` and keep sources with `source_type` equal to
   `GoogleSearchConsole`. If there is none, the project has not connected Search Console;
   say so and stop. Connecting it is a setup step in Data pipelines, not something to do
   from a query.
2. The HogQL name of each synced table is `googlesearchconsole.<table>`, or
   `googlesearchconsole.<prefix>.<table>` when the source was created with a prefix. Confirm
   the names and columns with `posthog:execute-sql`:
   `SELECT table_name, column_name, data_type FROM system.information_schema.columns WHERE table_name LIKE 'googlesearchconsole%'`.
   The source's schemas also carry each table's `hogql_name`. `read-data-schema` cannot
   inspect warehouse tables; it only answers event, entity and action property questions.
3. Tables restricted to image, video or news results carry a `_image`, `_video` or `_news`
   suffix. The bare name is web search.

## Tables and columns

| Table                                   | Dimensions                  | Synced by default |
| --------------------------------------- | --------------------------- | ----------------- |
| `search_analytics_by_date`              | `date`                      | no                |
| `search_analytics_by_query`             | `date`, `query`             | yes               |
| `search_analytics_by_page`              | `date`, `page`              | yes               |
| `search_analytics_by_query_page`        | `date`, `query`, `page`     | yes               |
| `search_analytics_by_country`           | `date`, `country`           | no                |
| `search_analytics_by_device`            | `date`, `device`            | no                |
| `search_analytics_by_country_device`    | `date`, `country`, `device` | no                |
| `search_analytics_by_page_device`       | `date`, `page`, `device`    | no                |
| `search_analytics_by_page_country`      | `date`, `page`, `country`   | no                |
| `search_analytics_by_query_device`      | `date`, `query`, `device`   | no                |
| `search_analytics_by_query_country`     | `date`, `query`, `country`  | no                |
| `search_analytics_by_hour`              | `date`, `hour`              | no                |
| `search_analytics_by_search_appearance` | `date`, `searchAppearance`  | no                |
| `sites`, `sitemaps`, `sitemap_contents` | property metadata snapshots | yes               |

Every `search_analytics_*` table carries the same metrics:

| Column              | Meaning                                                                            |
| ------------------- | ---------------------------------------------------------------------------------- |
| `date`              | The day, in Pacific time. Google publishes with a 2-3 day lag                      |
| `query`             | The search the user typed. Google withholds queries made by very few users         |
| `page`              | The canonical URL of the result page the user saw                                  |
| `clicks`            | Clicks that led to the property                                                    |
| `impressions`       | Times a link to the property appeared                                              |
| `ctr`               | `clicks / impressions`, a fraction between 0 and 1                                 |
| `position`          | Average position of the property's topmost result, 1 is the top                    |
| `search_type`       | `web`, `image`, `video` or `news`; null on rows imported before the column existed |
| `country`, `device` | ISO 3166-1 alpha-3 code; `DESKTOP`, `MOBILE` or `TABLET`                           |

Rules the marketing analytics runner follows, and you should too:

- Cast metrics: `toFloat(clicks)`, `toFloat(impressions)`, `toFloat(position)`.
- Filter dates with `toDate(date) >= toDate('...')`.
- Aggregate `position` weighted by impressions:
  `sum(toFloat(position) * toFloat(impressions)) / sum(toFloat(impressions))`. A plain
  `avg(position)` overweights rare queries.
- Match queries on `lower(trim(query))`.
- Normalize pages with `cutQueryStringAndFragment(page)` before joining to anything.
- Do not alias an aggregate to a source column name (`sum(...) AS impressions`): a later
  `toFloat(impressions)` in the same SELECT reads the alias, and ClickHouse rejects the
  aggregate inside an aggregate. The recipes use `gsc_clicks` and `gsc_impressions`.

Sampling: Google's API caps a table at about 50,000 rows per property, day and dimension
set, sorted by clicks, and drops the tail. `search_analytics_by_query_page` hits the cap
first. A long-tail query that is missing from the table may still exist in Search Console.

## Recipe: how do our cited pages rank on Google?

Pages the engines cite (from `target_urls`) joined to Search Console page performance.

```sql
WITH cited_pages AS (
    SELECT cutQueryStringAndFragment(url) AS page_url,
           uniqExact(prompt_id) AS citing_prompts,
           uniqExact(engine) AS citing_engines
    FROM (
        SELECT prompt_id,
               engine,
               arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(target_urls)))) AS url
        FROM system.aeo_citation_checks
        WHERE created_at >= now() - INTERVAL 30 DAY
          AND cited = 1
    )
    GROUP BY page_url
),
gsc_pages AS (
    SELECT cutQueryStringAndFragment(page) AS page_url,
           sum(toFloat(clicks)) AS gsc_clicks,
           sum(toFloat(impressions)) AS gsc_impressions,
           sum(toFloat(position) * toFloat(impressions)) / greatest(sum(toFloat(impressions)), 1) AS avg_position
    FROM googlesearchconsole.search_analytics_by_page
    WHERE toDate(date) >= toDate(now() - INTERVAL 30 DAY)
    GROUP BY page_url
)
SELECT c.page_url,
       c.citing_prompts,
       c.citing_engines,
       g.gsc_clicks,
       g.gsc_impressions,
       round(g.avg_position, 1) AS avg_position
FROM cited_pages AS c
LEFT JOIN gsc_pages AS g ON g.page_url = c.page_url
ORDER BY c.citing_prompts DESC
LIMIT 50
```

Null `gsc_clicks` means Search Console has no row for that URL: either it ranks for nothing,
or the canonical URL differs (trailing slash, `www`, http vs https). Check the variant before
concluding the page is invisible to Google.

Flip the join to find pages that rank well on Google but are never cited by an engine: start
from `gsc_pages`, `LEFT JOIN cited_pages`, keep `c.citing_prompts = 0`, order by
`gsc_impressions`. Test against zero, not null: `uniqExact` is not nullable, so an unmatched
row carries 0 and `IS NULL` returns nothing. Those are the pages where the content exists and
the citation does not.

## Recipe: do engine searches match the queries we rank for?

The engines record the web searches they ran in `search_queries`. Joining them to Search
Console `query` is approximate: engine searches are longer and more specific than what
people type into Google. Start exact, then widen, and say which level matched.

Exact match after normalization:

```sql
WITH engine_searches AS (
    SELECT lower(trim(q)) AS search_query,
           uniqExact(prompt_id) AS prompts,
           count() AS times
    FROM (
        SELECT prompt_id,
               arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(search_queries)))) AS q
        FROM system.aeo_citation_checks
        WHERE created_at >= now() - INTERVAL 30 DAY
          AND check_failed = 0
    )
    GROUP BY search_query
),
gsc_queries AS (
    SELECT lower(trim(query)) AS search_query,
           sum(toFloat(clicks)) AS gsc_clicks,
           sum(toFloat(impressions)) AS gsc_impressions,
           sum(toFloat(position) * toFloat(impressions)) / greatest(sum(toFloat(impressions)), 1) AS avg_position
    FROM googlesearchconsole.search_analytics_by_query
    WHERE toDate(date) >= toDate(now() - INTERVAL 30 DAY)
    GROUP BY search_query
)
SELECT e.search_query,
       e.prompts,
       e.times,
       g.gsc_clicks,
       g.gsc_impressions,
       round(g.avg_position, 1) AS avg_position
FROM engine_searches AS e
INNER JOIN gsc_queries AS g ON g.search_query = e.search_query
ORDER BY e.times DESC
LIMIT 50
```

Expect few exact hits. To widen, match a topic's keywords instead of the full search text:
pick two or three phrases from the topic's prompts and filter Search Console with
`multiSearchAnyCaseInsensitive(query, ['session replay', 'session recording'])`. Present the
result as "Google queries about this topic", not as a match to the engine's searches.

```sql
SELECT lower(trim(query)) AS search_query,
       sum(toFloat(clicks)) AS gsc_clicks,
       sum(toFloat(impressions)) AS gsc_impressions,
       round(sum(toFloat(position) * toFloat(impressions)) / greatest(sum(toFloat(impressions)), 1), 1) AS avg_position
FROM googlesearchconsole.search_analytics_by_query
WHERE toDate(date) >= toDate(now() - INTERVAL 30 DAY)
  AND multiSearchAnyCaseInsensitive(query, ['session replay', 'session recording'])
GROUP BY search_query
ORDER BY gsc_impressions DESC
LIMIT 50
```

## Recipe: topic scorecard

For each topic: citation rate from the engines, and the Google impressions and average
position of the pages those engines cite. Run the two sides separately and combine in your
answer; a single query joining on topic has no shared key, because Search Console knows
nothing about prompt topics.

1. Citation rate by topic from [citation-queries](./citation-queries.md).
2. Cited pages per topic: add `prompt_topic` to the "which of our pages get cited" recipe's
   inner query and `GROUP BY prompt_topic, url`.
3. Join those pages to `search_analytics_by_page` as above.

## What this join cannot tell you

- Search Console measures Google web search, not Google AI Overviews or AI Mode. A page can
  rank first and still never be cited by an answer engine, and the reverse.
- `date` is a Pacific-time day; `created_at` on checks is UTC. Compare windows, not days.
- Withheld low-volume queries and the row cap mean an absent query is not proof of zero
  impressions.
