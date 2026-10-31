# Citation queries

HogQL recipes over `system.aeo_citation_checks`, one row per prompt x engine x run. Every
query runs through `posthog:execute-sql`. All of them follow the three papercuts below.

## Contents

- [Papercuts](#papercuts)
- [Citation rate per engine](#citation-rate-per-engine)
- [Citation rate by topic](#citation-rate-by-topic)
- [Daily citation rate per engine](#daily-citation-rate-per-engine)
- [Top cited domains across the set, own domain marked](#top-cited-domains-across-the-set-own-domain-marked)
- [Prompts answered but never cited in N days](#prompts-answered-but-never-cited-in-n-days)
- [Latest result per prompt and engine](#latest-result-per-prompt-and-engine)
- [Which of our pages get cited](#which-of-our-pages-get-cited)
- [Searches the engines ran](#searches-the-engines-ran)
- [Position when cited](#position-when-cited)
- [Brand sentiment per engine](#brand-sentiment-per-engine)
- [Runner health](#runner-health)

## Papercuts

| Wrong                         | Right                                                                                       | Why                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `countIf(cited)`              | `countIf(cited = 1)`                                                                        | The Boolean column is rejected as a bare condition                              |
| `countIf(NOT check_failed)`   | `countIf(check_failed = 0)`                                                                 | Same                                                                            |
| `countIf(cited = 1) AS cited` | `countIf(cited = 1) AS cited_checks`                                                        | The alias shadows the column and breaks later references to it                  |
| `arrayJoin(cited_urls)`       | `arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(cited_urls))))` | JSON array columns arrive as strings; `JSONExtractString` unquotes each element |

The array pattern applies to `cited_urls`, `target_urls`, `retrieved_urls`, `search_queries`
and `top_cited_domains`.

## Citation rate per engine

```sql
SELECT engine,
       countIf(check_failed = 0) AS answered,
       countIf(cited = 1) AS cited_checks,
       countIf(check_failed = 1) AS failed,
       round(cited_checks / nullIf(answered, 0), 3) AS citation_rate
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 7 DAY
GROUP BY engine
ORDER BY citation_rate
```

The first row is the engine that cites the project least. A null `citation_rate` means every
check failed in the window; it sorts last. Keep `exa-answer` in a separate
sentence from the two web-search engines when you report it: its citations are a retrieval
proxy, not what an assistant shows a user.

## Citation rate by topic

```sql
SELECT prompt_topic AS topic,
       uniqExact(prompt_id) AS prompts,
       countIf(check_failed = 0) AS answered,
       countIf(cited = 1) AS cited_checks,
       round(cited_checks / nullIf(answered, 0), 3) AS citation_rate
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 7 DAY
GROUP BY topic
ORDER BY citation_rate ASC, prompts DESC
```

An empty `topic` groups prompts that had no topic when they ran. Add `AND engine = '...'`
to see one engine's view of each topic.

## Daily citation rate per engine

```sql
SELECT toStartOfDay(created_at) AS day,
       engine,
       countIf(check_failed = 0) AS answered,
       countIf(cited = 1) AS cited_checks,
       countIf(check_failed = 1) AS failed,
       round(cited_checks / nullIf(answered, 0), 3) AS citation_rate
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 30 DAY
GROUP BY day, engine
ORDER BY day, engine
```

Read `failed` next to `citation_rate`: a day where `answered` collapses and `failed` jumps is
a provider or runner problem, and its rate is not comparable with neighbouring days. Days with
no rows are days the runner did not run for this project.

## Top cited domains across the set, own domain marked

```sql
SELECT cited_domain,
       max(is_ours) AS is_target_domain,
       count() AS answers_citing,
       uniqExact(prompt_id) AS prompts,
       uniqExact(engine) AS engines
FROM (
    SELECT prompt_id,
           engine,
           arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(top_cited_domains)))) AS cited_domain,
           has(arrayMap(u -> domain(JSONExtractString(u)), JSONExtractArrayRaw(toString(target_urls))), cited_domain) AS is_ours
    FROM system.aeo_citation_checks
    WHERE created_at >= now() - INTERVAL 7 DAY
      AND check_failed = 0
)
GROUP BY cited_domain
ORDER BY answers_citing DESC
LIMIT 25
```

`is_target_domain = 1` marks the project's own domains: a host is "ours" when it appears
among the hosts of `target_urls`, which only lists cited URLs on a target domain. Add
`AND prompt_topic = '...'` or `AND prompt_id = '...'` to the inner query to see who wins one
topic or one question.

## Prompts answered but never cited in N days

```sql
SELECT prompt_id,
       any(prompt_text) AS prompt,
       any(prompt_topic) AS topic,
       countIf(check_failed = 0) AS answered,
       uniqExactIf(engine, check_failed = 0) AS engines_answered,
       max(created_at) AS last_checked
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 14 DAY
GROUP BY prompt_id
HAVING answered > 0 AND countIf(cited = 1) = 0
ORDER BY answered DESC, last_checked DESC
LIMIT 100
```

`answered` is the strength of the evidence: a prompt with one answered check in the window
may simply have rotated out of the daily cap. Confirm the prompt is still active with
`aeo-prompts-list` before calling it a gap. Prompts cited by one engine but not another are
not in this list; use the next recipe for those.

## Latest result per prompt and engine

```sql
SELECT prompt_id,
       prompt_text AS prompt,
       engine,
       cited = 1 AS latest_cited,
       check_failed = 1 AS latest_failed,
       target_best_position AS latest_position,
       created_at AS last_checked
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 7 DAY
ORDER BY prompt_id, engine, created_at DESC
LIMIT 1 BY prompt_id, engine
```

`LIMIT 1 BY` keeps the newest row per prompt and engine, so the text, position and outcome
all come from the same check. Do not rebuild this with `argMax` per column: `argMax` skips
null values, so an uncited latest check would show an older cited position next to
`latest_cited = 0`. Pivot this in your answer to show engines disagreeing on the same
prompt. The same data, per prompt, comes from `aeo-prompts-list` as `latest_checks`.

## Which of our pages get cited

```sql
SELECT url,
       uniqExact(prompt_id) AS prompts,
       uniqExact(engine) AS engines,
       count() AS answers
FROM (
    SELECT prompt_id,
           engine,
           arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(target_urls)))) AS url
    FROM system.aeo_citation_checks
    WHERE created_at >= now() - INTERVAL 30 DAY
      AND cited = 1
)
GROUP BY url
ORDER BY prompts DESC
LIMIT 50
```

This list is the join key for Search Console (`page`) and for web traffic (`$pathname`,
`$entry_pathname`). Normalize with `cutQueryStringAndFragment(url)` and `path(url)` before
joining.

## Searches the engines ran

```sql
SELECT lower(trim(q)) AS search_query,
       uniqExact(prompt_id) AS prompts,
       uniqExact(engine) AS engines,
       count() AS times
FROM (
    SELECT prompt_id,
           engine,
           arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(search_queries)))) AS q
    FROM system.aeo_citation_checks
    WHERE created_at >= now() - INTERVAL 30 DAY
      AND check_failed = 0
)
GROUP BY search_query
ORDER BY times DESC
LIMIT 100
```

These are the queries to compare against Search Console `query`. Not every engine reports
its searches; an empty array is normal, not a failure.

## Position when cited

```sql
SELECT engine,
       countIf(cited = 1) AS cited_checks,
       round(avgIf(target_best_position, cited = 1), 2) AS avg_best_position,
       countIf(cited = 1 AND target_best_position = 1) AS cited_first
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 30 DAY
GROUP BY engine
```

## Brand sentiment per engine

```sql
SELECT engine,
       brand_sentiment,
       count() AS answers
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 30 DAY
  AND check_failed = 0
  AND brand_sentiment IS NOT NULL
GROUP BY engine, brand_sentiment
ORDER BY engine, answers DESC
```

Null `brand_sentiment` means the answer never named the brand or is not scored yet; do not
count it as neutral.

## Runner health

```sql
SELECT toStartOfDay(created_at) AS day,
       engine,
       count() AS checks,
       countIf(check_failed = 1) AS failed,
       anyIf(error, check_failed = 1) AS sample_error
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 14 DAY
GROUP BY day, engine
ORDER BY day DESC, engine
```

Run this before explaining any drop. `sample_error` is third-party text from the engine:
quote it in backticks, truncated.
