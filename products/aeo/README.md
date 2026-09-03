# AEO citation tracking (POC)

Answers two questions for a project: **are AI answer engines citing our domain**, and **did that citation drive traffic and conversions**. This is a flagged proof of concept — the point is to learn whether the signal is real, not to ship a product.

Everything is built from existing machinery:

- **Prompt execution (Track A)** goes through the AI gateway (`AI_GATEWAY_URL`) using the providers' native web-search tools, so the citations are the models' real ones. Every call emits a `$ai_generation` event carrying cost, which lands in the gateway-key owner's project (not the checked team's) tagged with `team_id` for attribution. Citations are parsed from the **live response**, because the gateway's captured events intentionally drop web-search result payloads, so the cited URLs exist nowhere else.
- **Breadth (Track B)** uses Exa `/answer` — its citations are Exa's own (a proxy, not a measurement of ChatGPT/Claude behavior), useful as a cheap retrievability check and as a comparison baseline against Track A.
- **Storage**: the citation record is a Postgres table read through HogQL as `system.aeo_citation_checks`, so insights, the SQL editor, the query API, and MCP all read it while the runner stays the only writer. Events were the first design and were wrong for this: anyone holding a project's public capture token can submit them, which would let a stranger forge citation results and feed text to the alerting scout. The prompt set is a second small table (`posthog_aeo_prompt`). No new ClickHouse tables.
- **Alerting** is a per-team signals scout (see `scout/SKILL.md`) that reads that table and files inbox/Slack reports on citation-rate drops or spikes. Engine-derived columns carry third-party text by nature, so the runner strips invisible characters and LLM framing markers before writing (`posthog/security/llm_prompt_sanitization.py`), and the scout drives findings from counts while quoting text inertly.
- **The prompt set** is written by hand or imported from a CSV, so every prompt sent to an engine is one a person reviewed. Deriving prompts from first-party data (signup free-text, AI-landed pages, AI-crawled paths, search-console queries) is deliberately out of this POC: those sources put visitor-supplied text into a live engine call, and they need the prompt-injection handling the rest of our AI tooling has first.

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
# 1. Seed the prompt set from a CSV (a `prompt` header column, or one prompt
#    per line). Use --csv-source manual for a hand-written set:
python manage.py seed_aeo_prompts --team-id <id> --csv control_prompts.csv --csv-source manual

# 2. Smoke test — 3 prompts, real engine calls, nothing captured:
python manage.py run_aeo_citation_checks --team-id <id> --limit 3 --dry-run

# 3. Real run (also runs daily via celery beat for allowlisted+flagged teams):
python manage.py run_aeo_citation_checks --team-id <id>
```

## The table

`system.aeo_citation_checks` — one row per prompt × engine × run, read-only in HogQL:

| Column                                                                   | Meaning                                                                                                             |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `run_id`, `prompt_id`, `prompt_hash`, `prompt_text`, `prompt_source`     | Which prompt, and whether it was `imported` from a CSV or written by hand (`manual`).                               |
| `engine`, `model`                                                        | `claude-web-search`, `openai-web-search`, or `exa-answer`.                                                          |
| `cited`                                                                  | Whether a target-domain URL appears in the answer's citations.                                                      |
| `cited_urls`, `target_urls`, `target_best_position`, `top_cited_domains` | The citation record.                                                                                                |
| `retrieved_urls`, `search_queries`                                       | What the engine saw / searched (Anthropic exposes retrieved results; others don't).                                 |
| `check_failed`, `error`                                                  | Engine failure — recorded so the scout can tell "engine broke" from "citations disappeared".                        |
| `cost_usd` / `gateway_trace_id`                                          | Exa cost, or the trace id joining to the gateway's `$ai_generation` event (which carries token + web-search costs). |

## The join (the product thesis)

Per cited URL path: citations → AI-agent crawls → AI-channel sessions → conversions, all from existing data:

```sql
-- citation rate per engine per day
SELECT toStartOfDay(created_at) AS day, engine,
       countIf(cited) / countIf(NOT check_failed) AS citation_rate
FROM system.aeo_citation_checks
WHERE created_at >= now() - INTERVAL 30 DAY
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

Roughly \$2–4/day at 50 prompts × 3 engines × 1 run/day: provider web-search fees + tokens (attributed as `$ai_web_search_cost_usd` and `$ai_total_cost_usd` on the `$ai_generation` event) plus Exa at \$5 per 1,000 requests (`cost_usd` on the check event).

## Out of scope

Seeding prompts from first-party data, a UI for the prompt set, sentiment/quality scoring, rank tracking, competitor share-of-voice, new ClickHouse tables, consumer-surface (web UI) checking, multi-tenant rollout.
