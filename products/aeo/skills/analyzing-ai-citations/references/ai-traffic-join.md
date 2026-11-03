# Joining citations to AI traffic

Two signals in the project's own data say whether AI answers turn into visits. They come
from different tables and mean different things; report them separately.

| Signal              | Table      | Filter                            | What it measures                                               |
| ------------------- | ---------- | --------------------------------- | -------------------------------------------------------------- |
| AI referral session | `sessions` | `$channel_type = 'AI'`            | A person clicked through from an AI product to the site        |
| AI agent request    | `events`   | `$virt_traffic_type = 'AI Agent'` | An AI assistant, AI search engine or AI crawler fetched a page |

## Contents

- [AI referral sessions](#ai-referral-sessions)
- [AI agent requests](#ai-agent-requests)
- [The loop per cited path](#the-loop-per-cited-path)
- [Reading the loop](#reading-the-loop)

## AI referral sessions

`$channel_type` on `sessions` is derived from the entry referrer and UTM parameters. The
`AI` channel covers referrers such as `chatgpt.com`, `chat.openai.com`, `perplexity.ai`,
`claude.ai`, `gemini.google.com`, `copilot.microsoft.com`, `grok.com`, `deepseek.com`,
`meta.ai`, `poe.com`, `chat.mistral.ai`, `duck.ai`, `kimi.com`, `manus.im` and several
regional assistants. Use `$entry_referring_domain` for the breakdown.

Fields on `sessions`: `$channel_type`, `$entry_referring_domain`, `$entry_pathname`,
`$entry_current_url`, `$start_timestamp`, `$pageview_count`, `$session_duration`,
`$is_bounce`, `$end_pathname`.

```sql
SELECT toStartOfWeek($start_timestamp) AS week,
       $entry_referring_domain AS referrer,
       count() AS sessions,
       countIf($is_bounce = 1) AS bounces,
       round(avg($pageview_count), 1) AS pageviews_per_session
FROM sessions
WHERE $channel_type = 'AI'
  AND $start_timestamp >= now() - INTERVAL 90 DAY
GROUP BY week, referrer
ORDER BY week, sessions DESC
```

Landing pages of AI-referred sessions, to line up with cited URLs:

```sql
SELECT $entry_pathname AS landing_path,
       count() AS sessions,
       uniqExact($entry_referring_domain) AS referrers
FROM sessions
WHERE $channel_type = 'AI'
  AND $start_timestamp >= now() - INTERVAL 30 DAY
GROUP BY landing_path
ORDER BY sessions DESC
LIMIT 50
```

Caveat: most assistants open links without a referrer, or strip it. AI referral sessions
undercount; a cited page with zero AI sessions may still get AI-driven visits that land as
`Direct`.

## AI agent requests

The traffic classification reads the user agent (`$raw_user_agent`, falling back to
`$user_agent`) and the request IP against published bot ranges, and exposes the result as
virtual properties on `events`:

| Property                 | Values                                                                                        |
| ------------------------ | --------------------------------------------------------------------------------------------- |
| `$virt_traffic_type`     | `AI Agent`, `Bot`, `Automation`, `Regular`                                                    |
| `$virt_traffic_category` | `ai_assistant`, `ai_search`, `ai_crawler` (plus non-AI categories such as `search_crawler`)   |
| `$virt_bot_name`         | `ChatGPT`, `Claude User`, `OpenAI Search`, `Perplexity`, `GPTBot`, `Claude`, `Google AI`, ... |
| `$virt_bot_operator`     | `OpenAI`, `Anthropic`, `Perplexity`, `Google`, `Meta`, `Apple`, ...                           |
| `$virt_is_bot`           | `true` for every non-regular request                                                          |

The three AI categories answer different questions:

- `ai_assistant` (`ChatGPT`, `Claude User`, and similar user-triggered fetchers): an assistant
  read the page while answering someone. This is the closest thing to "a citation was shown".
- `ai_search` (`OpenAI Search`, `Perplexity`, `Apple AI`): an AI search index fetched the page.
  Precedes citations.
- `ai_crawler` (`GPTBot`, `Claude`, `Google AI`, `Common Crawl`, `Meta AI`): training or bulk
  crawling. Volume, not intent. The Meta crawler in particular fetches in bulk; exclude it
  with `$virt_bot_operator != 'Meta'` when you want a readable list.

Crawlers and assistants do not execute JavaScript, so `$pageview` never fires for them. The
project must forward server access logs as `$http_log` events carrying `$raw_user_agent`;
without that, the queries below return only the few agents that run a browser. If the user
asks why GPTBot is missing, the answer is almost always "no `$http_log` ingestion". The
`filtering-bot-traffic` skill covers that setup and custom bot rules.

```sql
SELECT $virt_traffic_category AS category,
       $virt_bot_name AS agent,
       $virt_bot_operator AS operator,
       count() AS requests,
       uniqExact(properties.$pathname) AS paths
FROM events
WHERE event IN ('$http_log', '$pageview', '$screen')
  AND $virt_traffic_type = 'AI Agent'
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY category, agent, operator
ORDER BY requests DESC
```

Which pages assistants read while answering:

```sql
SELECT properties.$pathname AS path,
       uniqExact($virt_bot_name) AS agents,
       count() AS fetches
FROM events
WHERE event = '$http_log'
  AND $virt_traffic_category = 'ai_assistant'
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY path
ORDER BY fetches DESC
LIMIT 50
```

## The loop per cited path

For each path the engines cite: how many prompts cite it, how often assistants fetched it,
how many AI-referred sessions landed on it, and how many of those converted. Replace
`'signed_up'` with the project's conversion event, or drop that column.

```sql
WITH cited AS (
    SELECT path(url) AS cited_path,
           uniqExact(prompt_id) AS citing_prompts,
           count() AS citing_answers
    FROM (
        SELECT prompt_id,
               arrayJoin(arrayMap(x -> JSONExtractString(x), JSONExtractArrayRaw(toString(target_urls)))) AS url
        FROM system.aeo_citation_checks
        WHERE created_at >= now() - INTERVAL 30 DAY
          AND cited = 1
    )
    GROUP BY cited_path
),
assistant_fetches AS (
    SELECT properties.$pathname AS fetched_path,
           count() AS fetches
    FROM events
    WHERE event = '$http_log'
      AND $virt_traffic_category = 'ai_assistant'
      AND timestamp >= now() - INTERVAL 30 DAY
    GROUP BY fetched_path
),
ai_sessions AS (
    SELECT $entry_pathname AS landing_path,
           count() AS sessions
    FROM sessions
    WHERE $channel_type = 'AI'
      AND $start_timestamp >= now() - INTERVAL 30 DAY
    GROUP BY landing_path
),
ai_conversions AS (
    SELECT e.session.$entry_pathname AS landing_path,
           uniqExact(e.$session_id) AS converting_sessions
    FROM events AS e
    WHERE e.event = 'signed_up'
      AND e.session.$channel_type = 'AI'
      AND e.timestamp >= now() - INTERVAL 30 DAY
    GROUP BY landing_path
)
SELECT c.cited_path,
       c.citing_prompts,
       c.citing_answers,
       f.fetches AS assistant_fetches,
       s.sessions AS ai_sessions,
       v.converting_sessions
FROM cited AS c
LEFT JOIN assistant_fetches AS f ON f.fetched_path = c.cited_path
LEFT JOIN ai_sessions AS s ON s.landing_path = c.cited_path
LEFT JOIN ai_conversions AS v ON v.landing_path = c.cited_path
ORDER BY c.citing_prompts DESC
LIMIT 50
```

Paths must match exactly on both sides. If the site serves `/docs/x` and `/docs/x/`, or the
engines cite URLs with query strings, normalize both sides the same way (`path()` already
drops the query string; add `trimRight(..., '/')` when trailing slashes differ).

## Reading the loop

- Citations without assistant fetches: the engines cite from their index, not from live
  reads. Not a contradiction.
- Assistant fetches without AI sessions: expected. Assistants show the citation; few people
  click, and most clicks carry no referrer.
- AI sessions on pages that are never cited: the person asked something outside the tracked
  prompt set. That is a candidate prompt to import, after the user confirms.
- A conversion count here is sessions that both entered from an AI referrer and fired the
  event; it is not attribution across sessions.
