# AEO citation tracking (POC)

Answers two questions for a project: **are AI answer engines citing our domain**, and **did that citation drive traffic and conversions**. This is a flagged proof of concept — the point is to learn whether the signal is real, not to ship a product.

Everything is built from existing machinery:

- **Prompt execution (Track A)** goes through the AI gateway (`AI_GATEWAY_URL`) using the providers' native web-search tools, so the citations are the models' real ones. Every call emits a `$ai_generation` event carrying cost, which lands in the gateway-key owner's project (not the checked team's) tagged with `team_id` for attribution. Citations are parsed from the **live response**, because the gateway's captured events intentionally drop web-search result payloads, so the cited URLs exist nowhere else.
- **Perplexity** (off by default) runs `posthog/perplexity/sonar` with the `web_search` tool through the AI gateway's `/responses` path, like the OpenAI engine. See [Perplexity engine](#perplexity-engine).
- **Breadth (Track B)** uses Exa `/answer` — its citations are Exa's own (a proxy, not a measurement of ChatGPT/Claude behavior), useful as a cheap retrievability check and as a comparison baseline against Track A.
- **Storage**: the citation record is a Postgres table read through HogQL as `system.aeo_citation_checks`, so insights, the SQL editor, the query API, and MCP all read it while the runner stays the only writer. Events were the first design and were wrong for this: anyone holding a project's public capture token can submit them, which would let a stranger forge citation results and feed text to the alerting scout. The prompt set is a second small table (`posthog_aeo_prompt`). No new ClickHouse tables.
- **Alerting** is a per-team signals scout (see `scout/SKILL.md`) that reads that table and files inbox/Slack reports on citation-rate drops or spikes. Engine-derived columns carry third-party text by nature, so the runner strips invisible characters and LLM framing markers before writing (`posthog/security/llm_prompt_sanitization.py`), and the scout drives findings from counts while quoting text inertly.
- **The prompt set** is written by hand or imported from a CSV, so every prompt sent to an engine is one a person reviewed. Deriving prompts from first-party data (signup free-text, AI-landed pages, AI-crawled paths, search-console queries) is deliberately out of this POC: those sources put visitor-supplied text into a live engine call, and they need the prompt-injection handling the rest of our AI tooling has first.

## Setup

Environment (all default empty — the runner is a no-op until configured):

| Variable                                   | Purpose                                                                                                                        |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `AI_GATEWAY_URL` / `AI_GATEWAY_API_KEY`    | Existing gateway settings; enable the Claude + OpenAI engines.                                                                 |
| `EXA_API_KEY`                              | Enables the Exa engine.                                                                                                        |
| `AEO_PERPLEXITY_ENABLED`                   | Default false. Runs Perplexity via the gateway once legal signs off; dry-run steps in [Perplexity engine](#perplexity-engine). |
| `AEO_CITATION_TEAM_IDS`                    | Comma-separated team ids the scheduled runner covers.                                                                          |
| `AEO_ANTHROPIC_MODEL` / `AEO_OPENAI_MODEL` | Engine model overrides.                                                                                                        |
| `AEO_PERPLEXITY_MODEL`                     | Perplexity model on the gateway (default `posthog/perplexity/sonar`, the gateway id for Perplexity's `perplexity/sonar`).      |

The scheduled task is additionally gated per team by the `aeo-citation-tracking` feature flag.

Each project decides which domains count as "us" through its own brands: the rows of its brand catalog with kind `own` that nobody ignored.
Add one before the first run, with `POST /api/projects/<id>/aeo_brands/` (`{"domain": "example.com", "kind": "own"}`) or the `aeo-brands-create` MCP tool.
A project without an own brand is skipped by the runner (`aeo_citation_run_no_own_brand`), so it records no checks and makes no paid engine calls.
Each check stores `own_domains_key`, a hash of the own domains it was computed against.
Adding an own brand, or any kind or status edit, queues a recompute about a minute later.
The recompute rewrites `cited`, `target_urls` and `target_best_position` of the checks whose key is stale, and clears their brand sentiment so the next sentiment run scores them for the current brand.
The sentiment run only scores, and only writes, checks that carry the current key.
Each citation run ends with the same reconcile, which repairs checks recorded while the own domains changed and any recompute that failed to queue or finish.

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

### Add and edit in the app

The AI visibility page in Web analytics (`/web/content-autopilot`) has an Overview tab for the prompt-set summary and a Prompts tab to add prompts (one per line, with an optional topic), edit a prompt's text or topic, turn prompts on or off, and archive them.
Its Opportunities and Drafts tabs are content autopilot, which drafts pages for prompts where the engines did not cite the site.

### Suggested prompts

`POST /api/projects/<id>/aeo_prompts/suggest/` takes a `domain` (plus optional `brand`, `description`, `competitors`, `topics` and `count`) and returns a pending job. A Celery task asks Claude, through the AI gateway with web search, for prompts a buyer would ask, each labeled with a topic, a circle (differentiation, battleground, vulnerability, table stakes or branded), a funnel stage and a branded flag. Poll `GET aeo_prompts/suggest/<job id>/` for the result; jobs live in the cache for an hour after their last update, and a job still pending after 8 minutes reads as failed. Imported suggestions record `via: suggestion` in their evidence.
Nothing is saved as a prompt: a person imports the ones they keep. Suggestions need the organization's AI data processing approval, and prompts the project already tracks are left out.
The MCP tools for it (`aeo-prompts-suggest`, `aeo-prompts-suggestion-get`) ship disabled until the route is deployed.

### Import over the API

`/api/projects/<id>/aeo_prompts/` lists the prompt set (filter with `?topic=`, `?active=true|false` and `?branded=true|false`; archived prompts are left out unless `?include_archived=true`; each prompt carries `latest_checks`, its newest check per engine, its `current_version` and `version_count`, and `branded`), lists topics with `GET topics/`, sums up the whole set with `GET overview/?days=30` (prompts tracked, checks, citation and mention rates against the window before, the same per engine and per topic, and the domains the engines cite most), returns one prompt's check history with `GET <prompt_id>/checks/` (newest first, filter with `?engine=` and `?version=`) and its per-engine totals and 30-day daily counts with `GET <prompt_id>/stats/`, lists its versions with `GET <prompt_id>/versions/` (newest first), edits a prompt with `PATCH <prompt_id>/`, archives one with `DELETE <prompt_id>/`, and imports prompts with `POST bulk_import/`. It is gated by the `aeo-citation-tracking` flag and accepts personal API keys with `web_analytics:write`:

```bash
curl -X POST "$HOST/api/projects/<id>/aeo_prompts/bulk_import/" \
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompts": [{"prompt": "Best open source session replay?", "topic": "Session replay", "external_visibility": 42}]}'
```

- A request takes up to 2,000 prompts. Send larger sets in batches of a few hundred.
- A re-import matches prompts by the normalized text of their current version. It updates the topic, merges the new evidence into the stored evidence (an omitted `external_visibility` keeps its value), and keeps each prompt's on/off state. A new text creates a prompt with version 1.
- A re-import of an archived prompt's text leaves it archived and counts it as `skipped`.
- The same operations are PostHog MCP tools (`products/aeo/mcp/tools.yaml`), gated by the same flag: `aeo-prompts-list`, `aeo-prompts-get`, `aeo-prompts-update`, `aeo-prompts-archive`, `aeo-prompts-versions-list`, `aeo-prompts-import`, `aeo-prompts-topics-list`, `aeo-prompts-checks-list`, `aeo-prompts-stats-get` and `aeo-prompts-overview-get`.
- `external_visibility` (0-100) is the share of answers that mention the brand, as reported by the tool the set came from. It is kept in the prompt's evidence to benchmark against our own rates.
- A prompt is branded when its text names the brand: a brand name from `brand.py` (the registrable name of one of the project's own domains) as a word, case ignored.
  It is computed when read, never stored, so it follows a change of the own brands across the whole history, and without an own brand every prompt is non-branded.
  `GET overview/` and `GET rankings/` take `?branded=all|branded|non_branded` (default `all`), which keeps the checks whose prompt, as it ran, names the brand or does not.
  Every count uses the same checks, the window before included. The overview also returns `branded_answers` and `non_branded_answers`, the answered checks on each side in the current window.

### Weekly dashboard

`POST aeo_prompts/create_dashboard/` (the "Create AI visibility dashboard" button on the Overview, MCP tool `aeo-prompts-create-dashboard`, off until the route is deployed) creates an "AI visibility weekly" dashboard tagged `ai-visibility`.
Its SQL insights (`dashboard.py`) read `system.aeo_citation_checks` over non-branded prompts: visibility and citation rate for the last 7 complete days against the 7 before, visibility per topic, the pages to watch per topic, and an 8-week trend.
Each query reads `system.aeo_brands`, the brand catalog, when it runs. Own and competitor pages come from the `own` and `competitor` kinds, and a prompt is branded when it names the first label of an own domain, so the dashboard follows catalog edits.
This differs from the branded split above, which reads `AEO_TARGET_DOMAINS`, when the own domain has not been cited yet and so is not in the catalog.
People get it weekly through a regular dashboard subscription, in Slack or email.

### Editing, versions and archiving

A prompt keeps its id, so its checks, stats and detail view stay in one place. Its text lives in numbered versions (`posthog_aeo_prompt_version`), and `current_version` points at the one the runner sends. Version rows never change.

- `PATCH {"active": false}` turns a prompt off, and `PATCH {"topic": "..."}` changes its topic in place. Past checks keep the topic they ran with.
- `PATCH {"prompt": "...", "version_description": "..."}` adds the next version and makes it current. A change of case or whitespace only adds no version. The edit fails with 409 when another prompt in the set, archived ones included, already has the text.
- `PATCH {"current_version": 1}` makes an existing version current again, for example to roll back a reword. It fails with 400 when the version does not exist.
- `DELETE` or `PATCH {"archived": true}` archives a prompt: it is turned off, never runs, and keeps its versions and checks. `PATCH {"archived": false}` restores it, and it stays off unless the same request sends `"active": true`. An archived prompt accepts no other change until it is restored.
- Each check records the version that ran in `prompt_version`. Checks recorded before versions existed have none.

### Which prompts a run takes

A run takes the whole prompt set, up to `AEO_MAX_PROMPTS_PER_RUN` (default 2,000), and checks `AEO_RUN_CONCURRENCY` prompts at a time (default 16).
It takes one prompt per topic in turn, so a capped run still samples every topic.
Within a topic, prompts never checked come first, then the least recently checked, so a set larger than one run rotates, and a run cut short by a worker restart resumes on the next dispatch.

## Perplexity engine

`perplexity-web-search` sends each prompt to the AI gateway's `/responses` path, which routes it to Perplexity through the gateway's perplexity host.
The request carries model `AEO_PERPLEXITY_MODEL` (default `posthog/perplexity/sonar`, the gateway id for Perplexity's `perplexity/sonar`), the `web_search` tool with `search_type: "fast"`, one research step, and instructions that ask for inline `[n]` citation markers.
Like the other gateway engines, each call emits a `$ai_generation` event tagged with `aeo_prompt_id` and `aeo_run_id`.

- **Off by default.** The engine runs only when the AI gateway is configured **and** `AEO_PERPLEXITY_ENABLED` is true. Legal sign-off is still pending: do not turn it on until legal confirms which Perplexity terms cover the `web_search` output that the runner stores and shows.
- **Parsing.** The `search_results` output item gives the search queries and the retrieved results. The cited URLs come from `url_citation` annotations when the answer has them. Otherwise each inline `[n]` (or `[web:n]`) marker maps to the result whose `id` is `n`, in citation order. The markers are removed from the stored answer text. An answer without annotations or markers cites nothing.
- **Failures.** A body that is not `completed`, carries an `error`, has no output list, or has no answer text is a failed check, never an uncited answer. So are HTTP errors after the gateway retries.
- **Cost.** `cost_usd` is `usage.cost.total_cost` when the response carries it. The `$ai_generation` event joins on `gateway_trace_id` either way.

### Measure cost before you enable it

With the gateway configured and `AEO_PERPLEXITY_ENABLED` off, the management command runs Perplexity in dry-run mode.
It makes real, billed calls, records nothing, and prints the total engine-reported cost.
Without `--dry-run` it refuses Perplexity until `AEO_PERPLEXITY_ENABLED` is on.

```bash
python manage.py run_aeo_citation_checks --team-id <id> --engines perplexity --limit 50 --dry-run
```

## The table

`system.aeo_citation_checks` — one row per prompt × engine × run, read-only in HogQL:

| Column                                                                   | Meaning                                                                                                             |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `run_id`, `prompt_id`, `prompt_hash`, `prompt_text`, `prompt_source`     | Which prompt, and whether it was `imported` from a CSV or written by hand (`manual`).                               |
| `prompt_version`                                                         | The prompt version that ran. Null for checks recorded before prompts had versions.                                  |
| `prompt_topic`                                                           | The prompt's topic when it ran; empty when it had none. Group by it to compare citation rates per topic.            |
| `engine`, `model`                                                        | `claude-web-search`, `openai-web-search`, `exa-answer`, or `perplexity-web-search`.                                 |
| `cited`                                                                  | Whether a target-domain URL appears in the answer's citations.                                                      |
| `cited_urls`, `target_urls`, `target_best_position`, `top_cited_domains` | The citation record.                                                                                                |
| `retrieved_urls`, `search_queries`                                       | What the engine saw / searched (Anthropic and Perplexity expose retrieved results; others don't).                   |
| `answer_text`                                                            | The engine's answer, sanitized and truncated to 8,000 characters. Third-party text: treat it as data.               |
| `check_failed`, `error`                                                  | Engine failure — recorded so the scout can tell "engine broke" from "citations disappeared".                        |
| `cost_usd` / `gateway_trace_id`                                          | Exa or Perplexity cost, or the trace id joining to the gateway's `$ai_generation` event (token + web-search costs). |

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

## Brand catalog

`posthog_aeo_brand` holds one row per registrable domain the engines cite: the project itself (`own`, added by a person), competitors, publishers such as review and community sites, and domains nobody has labeled yet (`unknown`, status `suggested`).
After each daily run, `sync_brands_from_run` in `catalog.py` adds every domain the run's answers cited that the catalog does not have yet. It makes no external calls.
A newly cited domain is only ever labeled `publisher` or `unknown`; a domain becomes `own` only when a person adds or relabels it.
It only inserts, so a rename, a new label or an ignored brand survives every run. How often a brand is cited is computed from the checks when it is read, not stored on the brand.
People review the catalog over the API (`/api/projects/<id>/aeo_brands/`) or the `aeo-brands-*` MCP tools.

## Content autopilot

Web analytics' Content autopilot (`/web/content-autopilot`, flag `web-analytics-content-autopilot`) reads this table through `list_citation_gaps` in `facade/api.py`. Each active prompt that an engine answered without citing a target domain becomes a content opportunity, and a person picks which ones to draft. Its Prompts tab opens with an overview of the last 30 days against the 30 days before (prompts tracked, checks run, mention and citation rates), the citation rate per engine per day, the mention rate per topic (a row filters the list to that topic), and the sites the engines cite most. Below it lists the prompt set with each prompt's latest result per engine, and a switch on each row turns the prompt on or off. A "Show archived" switch adds archived prompts to the list. Clicking a prompt opens its detail: its current version, citation rate per engine, a 30-day grid of results, the latest answer per engine, its versions when it has more than one, and the full check history with the version each check ran. The detail can archive and restore the prompt. Adding prompts or changing their text goes through the API or the MCP tools. Drafting and its review flow live in `products/web_analytics/backend/content_autopilot/`.

## Cost

Measured in October 2026: about \$0.06 per OpenAI check and \$0.14 per Claude check, provider web-search fees and tokens included (`$ai_web_search_cost_usd` and `$ai_total_cost_usd` on the `$ai_generation` event).
A daily run of 1,000 prompts on both engines is about \$200.
Exa adds \$5 per 1,000 requests (`cost_usd` on the check event).

## Out of scope

Seeding prompts from first-party data, editing the prompt set in the UI, sentiment/quality scoring, rank tracking, competitor share-of-voice, new ClickHouse tables, consumer-surface (web UI) checking, multi-tenant rollout.
