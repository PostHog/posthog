# AEO citation tracking (POC)

Answers two questions for a project: **are AI answer engines citing our domain**, and **did that citation drive traffic and conversions**. This is a flagged proof of concept — the point is to learn whether the signal is real, not to ship a product.

Everything is built from existing machinery:

- **Prompt execution (Track A)** goes through the AI gateway (`AI_GATEWAY_URL`) using the providers' native web-search tools, so the citations are the models' real ones and every call gets cost attribution on its `$ai_generation` event for free. Citations are parsed from the **live response** — the gateway's captured events intentionally drop web-search result payloads, so the cited URLs exist nowhere else.
- **Breadth (Track B)** uses Exa `/answer` — its citations are Exa's own (a proxy, not a measurement of ChatGPT/Claude behavior), useful as a cheap retrievability check and as a comparison baseline against Track A.
- **Storage** is ordinary events: one `$aeo_citation_check` event per prompt × engine × run. No new tables.
- **Alerting** is a per-team signals scout (see `scout/SKILL.md`) that reads those events and files inbox/Slack reports on citation-rate drops or spikes.

## Setup

Environment (all default empty — the runner is a no-op until configured):

| Variable                                   | Purpose                                                        |
| ------------------------------------------ | -------------------------------------------------------------- |
| `AI_GATEWAY_URL` / `AI_GATEWAY_API_KEY`    | Existing gateway settings; enable the Claude + OpenAI engines. |
| `EXA_API_KEY`                              | Enables the Exa engine.                                        |
| `AEO_CITATION_TEAM_IDS`                    | Comma-separated team ids the scheduled runner covers.          |
| `AEO_TARGET_DOMAINS`                       | Domains counted as "us" in citations (default `posthog.com`).  |
| `AEO_ANTHROPIC_MODEL` / `AEO_OPENAI_MODEL` | Engine model overrides.                                        |

The scheduled task is additionally gated per team by the `aeo-citation-tracking` feature flag.

## Usage

```bash
# 1. Seed prompts from first-party data (add --expand to derive prompts from
#    AI-landed and AI-crawled pages via one gateway LLM call):
python manage.py seed_aeo_prompts --team-id <id> --expand

# Add a hand-written control set (the baseline seeding must beat):
python manage.py seed_aeo_prompts --team-id <id> --csv control_prompts.csv --csv-source manual

# 2. Smoke test — 3 prompts, real engine calls, nothing captured:
python manage.py run_aeo_citation_checks --team-id <id> --limit 3 --dry-run

# 3. Real run (also runs daily via celery beat for allowlisted+flagged teams):
python manage.py run_aeo_citation_checks --team-id <id>
```

## The event

`$aeo_citation_check` — one per prompt × engine × run:

| Property                                                                 | Meaning                                                                                                                           |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `aeo_run_id`, `prompt_id`, `prompt_hash`, `prompt_text`, `prompt_source` | Which prompt, from which seeding source (`user_reported`, `ai_entry_page`, `crawled_content`, `gsc_query`, `imported`, `manual`). |
| `engine`, `model`                                                        | `claude-web-search`, `openai-web-search`, or `exa-answer`.                                                                        |
| `cited`                                                                  | Whether a target-domain URL appears in the answer's citations.                                                                    |
| `cited_urls`, `target_urls`, `target_best_position`, `top_cited_domains` | The citation record.                                                                                                              |
| `retrieved_urls`, `search_queries`                                       | What the engine saw / searched (Anthropic exposes retrieved results; others don't).                                               |
| `check_failed`, `error`                                                  | Engine failure — kept as events so the scout can tell "engine broke" from "citations disappeared".                                |
| `cost_usd` / `gateway_trace_id`                                          | Exa cost, or the trace id joining to the gateway's `$ai_generation` event (which carries token + web-search costs).               |

## The join (the product thesis)

Per cited URL path: citations → AI-agent crawls → AI-channel sessions → conversions, all from existing data:

```sql
-- citation rate per engine per day
SELECT toStartOfDay(timestamp) AS day, properties.engine AS engine,
       countIf(properties.cited = 'true') / countIf(properties.check_failed = 'false') AS citation_rate
FROM events
WHERE event = '$aeo_citation_check' AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day, engine ORDER BY day

-- crawls for a cited path (asset noise and bulk fetchers excluded)
SELECT count() FROM events
WHERE event = '$http_log' AND `$virt_traffic_type` = 'AI Agent' AND `$virt_bot_operator` != 'Meta'
  AND properties.$pathname = '/docs/session-replay' AND timestamp >= now() - INTERVAL 7 DAY

-- AI-channel sessions landing on that path
SELECT count() FROM sessions
WHERE $channel_type = 'AI' AND $entry_pathname = '/docs/session-replay'
  AND $start_timestamp >= now() - INTERVAL 30 DAY
```

## Cost

Roughly $2–4/day at 50 prompts × 3 engines × 1 run/day: provider web-search fees + tokens (attributed as `$ai_web_search_cost_usd` / `$ai_total_cost_usd` on the `$ai_generation` event) plus Exa at $5 per 1,000 requests (`cost_usd` on the check event).

## Out of scope

Sentiment/quality scoring, rank tracking, competitor share-of-voice, new ClickHouse tables, consumer-surface (web UI) checking, multi-tenant rollout.
