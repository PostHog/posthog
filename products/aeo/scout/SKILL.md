---
name: signals-scout-aeo-citations
description: Watches AEO citation-check results ($aeo_citation_check events) and files an inbox report when a domain's citation rate on an answer engine drops or spikes versus its baseline, or when the citation runner itself is failing.
allowed_tools:
  - emit_report
  - edit_report
metadata:
  owner_team: web-analytics
  scope: aeo
---

<!--
POC scout — deliberately NOT under products/signals/skills/ so it is never
auto-seeded fleet-wide. Register it per-team on the pilot project through the
skills-store path (scout-create-prepare / scout-create-execute API, with this
file's frontmatter and body as the skill), leaving default trusted network
access and a daily cadence scheduled after the citation runner's daily run.
Test a run locally with `python manage.py run_signals_scout`.
-->

# AEO citation-rate watch

You watch the results of scheduled AEO citation checks and report when the
signal changes materially. You do not run citation checks yourself — a backend
runner executes the prompt set daily and captures one `$aeo_citation_check`
event per prompt × engine.

## Quick close-out

Run this first; if it hits, save a memory and stop:

```sql
SELECT count() FROM events WHERE event = '$aeo_citation_check' AND timestamp >= now() - INTERVAL 14 DAY
```

If zero, the runner isn't active on this project — nothing to watch. Remember
`noise:aeo:no-runner` with today's date and close out. (Re-check on later runs;
delete the memory once data appears.)

## Orient

Compute the per-engine daily citation rate, failure rate, and volume:

```sql
SELECT toStartOfDay(timestamp) AS day, properties.engine AS engine,
       countIf(properties.check_failed = 'false') AS checks,
       countIf(properties.check_failed = 'true') AS failed,
       countIf(properties.cited = 'true') AS cited,
       cited / greatest(checks, 1) AS citation_rate
FROM events
WHERE event = '$aeo_citation_check' AND timestamp >= now() - INTERVAL 21 DAY
GROUP BY day, engine
ORDER BY engine, day
```

Read your scratchpad for `pattern:aeo:<engine>` baselines (mean citation rate
and typical daily check count over the trailing window). If no baseline exists
yet, save one per engine and close out — the first run establishes baselines,
it does not report.

## Decide

For each engine with an established baseline, compare the most recent complete
day against the baseline:

- **Drop**: citation rate below 60% of baseline for the latest day, with at
  least 10 successful checks that day. This is the "engine stopped citing us"
  case worth an immediate report.
- **Spike**: citation rate above 150% of baseline with at least 10 successful
  checks — worth reporting as a win (what changed? which prompts flipped?).
- **Runner health**: failure rate (`failed / (checks + failed)`) above 30% for
  the latest day. Report as an operational issue, clearly labelled as "the
  checker is failing", NOT as a citation change.

Disqualifiers — do not report when:

- The latest day has fewer than 10 successful checks for that engine (the
  prompt set was truncated or the runner ran partially — note it in memory).
- The change is explained by a change in the prompt set itself: compare
  `uniq(properties.prompt_hash)` day-over-day; if the prompt set changed by
  more than 20%, baseline is invalid — reset `pattern:aeo:<engine>` instead.
- An open report already covers this engine's incident (check
  `report:aeo:<engine>` in memory and the inbox first) — edit it with the new
  data instead of filing a duplicate.

## Report

One report per engine incident. Include: the engine, the citation rate vs
baseline, the day it changed, which prompts lost/gained citations (top 5 by
`prompt_text`, with their `prompt_source`), and — for drops — whether the
affected prompts' previously cited `target_urls` still receive AI-agent crawls
(`$http_log` where `$virt_traffic_type = 'AI Agent'`) and AI-channel sessions
(`sessions.$channel_type = 'AI'`), so the reader sees whether traffic is
following the citation change. Route to the team member who owns AEO if the
member roster identifies one; otherwise leave unassigned.

After filing or editing, update memory: `report:aeo:<engine>` with the report
id, and refresh `pattern:aeo:<engine>` with the new baseline window.

## Close-out

Always refresh `pattern:aeo:<engine>` baselines (rolling 14-day mean excluding
the anomalous day, if any) before finishing, so the next run compares against
current reality.
