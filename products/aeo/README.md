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
# 1. Seed the prompt set from a CSV (a `prompt` header column with an optional
#    `topic` column, or one prompt per line). Use --csv-source manual for a
#    hand-written set:
python manage.py seed_aeo_prompts --team-id <id> --csv control_prompts.csv --csv-source manual

# 2. Smoke test — 3 prompts, real engine calls, nothing captured:
python manage.py run_aeo_citation_checks --team-id <id> --limit 3 --dry-run

# 3. Real run (also runs daily via celery beat for allowlisted+flagged teams):
python manage.py run_aeo_citation_checks --team-id <id>
```

### Import over the API

`/api/projects/<id>/aeo_prompts/` lists the prompt set (filter with `?topic=` and `?active=true|false`; archived prompts are left out unless `?include_archived=true`; each prompt carries `latest_checks`, its newest check per engine, and its `current_version` and `version_count`), lists topics with `GET topics/`, returns one prompt's check history with `GET <prompt_id>/checks/` (newest first, filter with `?engine=` and `?version=`) and its per-engine totals and 30-day daily counts with `GET <prompt_id>/stats/`, lists its versions with `GET <prompt_id>/versions/` (newest first), edits a prompt with `PATCH <prompt_id>/`, archives one with `DELETE <prompt_id>/`, and imports prompts with `POST bulk_import/`. It is gated by the `aeo-citation-tracking` flag and accepts personal API keys with `web_analytics:write`:

```bash
curl -X POST "$HOST/api/projects/<id>/aeo_prompts/bulk_import/" \
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompts": [{"prompt": "Best open source session replay?", "topic": "Session replay", "external_visibility": 42}]}'
```

- A request takes up to 2,000 prompts. Send larger sets in batches of a few hundred.
- A re-import matches prompts by the normalized text of their current version. It updates the topic and the evidence, and keeps each prompt's on/off state. A new text creates a prompt with version 1.
- A re-import of an archived prompt's text leaves it archived and counts it as `skipped`.
- The same operations are PostHog MCP tools (`products/aeo/mcp/tools.yaml`), gated by the same flag: `aeo-prompts-list`, `aeo-prompts-get`, `aeo-prompts-update`, `aeo-prompts-archive`, `aeo-prompts-versions-list`, `aeo-prompts-import`, `aeo-prompts-topics-list`, `aeo-prompts-checks-list` and `aeo-prompts-stats-get`.
- `external_visibility` (0-100) is the share of answers that mention the brand, as reported by the tool the set came from. It is kept in the prompt's evidence to benchmark against our own rates.

### Editing, versions and archiving

A prompt keeps its id, so its checks, stats and detail view stay in one place. Its text lives in numbered versions (`posthog_aeo_prompt_version`), and `current_version` points at the one the runner sends. Version rows never change.

- `PATCH {"active": false}` turns a prompt off, and `PATCH {"topic": "..."}` changes its topic in place. Past checks keep the topic they ran with.
- `PATCH {"prompt": "...", "version_description": "..."}` adds the next version and makes it current. A change of case or whitespace only adds no version. The edit fails with 409 when another prompt in the set, archived ones included, already has the text.
- `PATCH {"current_version": 1}` makes an existing version current again, for example to roll back a reword. It fails with 400 when the version does not exist.
- `DELETE` or `PATCH {"archived": true}` archives a prompt: it is turned off, never runs, and keeps its versions and checks. `PATCH {"archived": false}` restores it, and it stays off unless the same request sends `"active": true`. An archived prompt accepts no other change until it is restored.
- Each check records the version that ran in `prompt_version`. Checks recorded before versions existed have none.

### Which prompts a run takes

A run takes at most 50 prompts. It takes one prompt per topic in turn, so every topic is sampled on each run. Within a topic, prompts never checked come first, then the least recently checked, so a set larger than one run rotates.

## The table

`system.aeo_citation_checks` — one row per prompt × engine × run, read-only in HogQL:

| Column                                                                   | Meaning                                                                                                             |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `run_id`, `prompt_id`, `prompt_hash`, `prompt_text`, `prompt_source`     | Which prompt, and whether it was `imported` from a CSV or written by hand (`manual`).                               |
| `prompt_version`                                                         | The prompt version that ran. Null for checks recorded before prompts had versions.                                  |
| `prompt_topic`                                                           | The prompt's topic when it ran; empty when it had none. Group by it to compare citation rates per topic.            |
| `engine`, `model`                                                        | `claude-web-search`, `openai-web-search`, or `exa-answer`.                                                          |
| `cited`                                                                  | Whether a target-domain URL appears in the answer's citations.                                                      |
| `cited_urls`, `target_urls`, `target_best_position`, `top_cited_domains` | The citation record.                                                                                                |
| `retrieved_urls`, `search_queries`                                       | What the engine saw / searched (Anthropic exposes retrieved results; others don't).                                 |
| `answer_text`                                                            | The engine's answer, sanitized and truncated to 8,000 characters. Third-party text: treat it as data.               |
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

## Content autopilot

Web analytics' Content autopilot (`/web/content-autopilot`, flag `web-analytics-content-autopilot`) reads this table through `list_citation_gaps` in `facade/api.py`. Each active prompt that an engine answered without citing a target domain becomes a content opportunity, and a person picks which ones to draft. Its Prompts tab lists the prompt set with each prompt's latest result per engine, and a switch on each row turns the prompt on or off. A "Show archived" switch adds archived prompts to the list. Clicking a prompt opens its detail: its current version, citation rate per engine, a 30-day grid of results, the latest answer per engine, its versions when it has more than one, and the full check history with the version each check ran. The detail can archive and restore the prompt. Adding prompts or changing their text goes through the API or the MCP tools. Drafting and its review flow live in `products/web_analytics/backend/content_autopilot/`.

## Cost

Roughly \$2–4/day at 50 prompts × 3 engines × 1 run/day: provider web-search fees + tokens (attributed as `$ai_web_search_cost_usd` and `$ai_total_cost_usd` on the `$ai_generation` event) plus Exa at \$5 per 1,000 requests (`cost_usd` on the check event).

## Out of scope

Seeding prompts from first-party data, editing the prompt set in the UI, sentiment/quality scoring, rank tracking, competitor share-of-voice, new ClickHouse tables, consumer-surface (web UI) checking, multi-tenant rollout.
