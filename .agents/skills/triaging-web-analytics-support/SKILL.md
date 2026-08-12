---
name: triaging-web-analytics-support
description: >
  Triage web analytics support tickets end to end: enumerate open tickets from
  the in-app conversations product and their Zendesk mirrors, classify each
  into a diagnostic shape (frontend crash, "two numbers don't match", traffic
  count drop, tracker not loading / undercounting vs a competitor, ad-platform
  integration error, channel type misclassification), run the matching
  playbook, and produce reply drafts plus fix PRs where warranted. Use when
  asked to triage the web analytics support channel, investigate a web
  analytics Zendesk or conversations ticket, or explain metric discrepancies a
  customer reported. Internal-only: queries cross-customer support and usage
  data; never copy customer names or their traffic numbers into public
  artifacts (PRs, issues, commits).
---

# Triaging web analytics support tickets

The job: turn a pile of open support tickets into (a) reply drafts grounded in code or data, and (b) draft PRs for real bugs.
Most reported "bugs" are explainable semantics; most real bugs show up in error tracking or raw data before they show up in the code.
Diagnose before writing code, and always determine which layer a symptom lives in before proposing a fix.

## 1. Enumerate the queue

Tickets live in the conversations product and are queryable via the PostHog MCP `execute-sql` tool against `system.support_tickets` (project 2, US).
Zendesk mirrors carry full comment history in the data warehouse.
See [references/ticket-queries.md](references/ticket-queries.md) for ready-to-run SQL: open-ticket scans, keyword filters, full Zendesk comment extraction (the `child_events` JSON pattern), and resolving a requester email to an org/team across US and EU regions.

Slack channel `#support-web-analytics` mirrors new Zendesk tickets; the in-app ticket link in each message carries the conversations UUID.

## 2. Classify the shape, then run its playbook

Detailed walk-throughs with worked examples are in [references/diagnostic-playbooks.md](references/diagnostic-playbooks.md). The shapes:

| Shape                                        | Trigger phrases                                                 | First move                                                                                                                                                                                      |
| -------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend crash                               | "everything crashes", exception ID, stack trace                 | Error tracking lookup; sourcemapped frames name the file. Check both US and EU projects                                                                                                         |
| Two numbers don't match                      | "two different bounce rates", "insight X disagrees with tile Y" | Semantics first, not code: event-level vs session-entry scoping, "landing vs containing", any-event vs entry-event filters explain most of these                                                |
| Count drop over time                         | "pageviews declined", "tracking loss"                           | Layer split: raw stored counts vs query-side exclusion. `$pageview` vs `$pageleave` ratio, UA segmentation, SDK version pin. Bot-shaped traffic disappearing is common and is not a PostHog bug |
| Tracker not loading / undercounts competitor | "numbers lower than <other tool>", GTM, consent, ad blockers    | Runtime loading audit with Playwright against their live site: load method, first-request timing, blocklist simulation. See [references/loading-audit.md](references/loading-audit.md)          |
| Ad-platform integration error                | "can't re-add source", OAuth errors, "no conversions"           | Source re-creation paths, OAuth failure modes (for example Microsoft AADSTS650052), attribution join keys (exact campaign name + normalized source, both UTMs required for the fallback)        |
| Channel type misclassification               | "shows as Direct", "wrong channel"                              | `posthog/models/channel_type/channel_definitions.json` + the decision tree in `posthog/hogql/database/schema/channel_type.py`; unknown source + stripped referrer falls through to Direct       |

Two cross-cutting rules:

- **Determine the layer before the fix.** Capture → ingestion → stored events → query-time classification → UI. A drop in raw `count()` can't be caused by query-time bot exclusion; a classification change can't alter stored counts. State which layer the evidence points at.
- **Check for prior art before building.** Search open issues/PRs and the channel history; several recurring asks (self-referral exclusion, AI channel type, OAuth error surfacing) have open issues with context that changes the right response.

## 3. Produce artifacts

- **Reply drafts**: ground every claim in a file:line, a query result, or a doc link. Offer the customer the aligned filter/property instead of only explaining why they're "wrong" (for example: session `$entry_utm_campaign` instead of event `utm_campaign`).
- **Fix PRs**: one worktree + branch per fix, conventional commit, draft PR using the repo template. Public-repo safety: describe bugs generically; never include customer names, Zendesk numbers, or customer traffic volumes. Slack/ticket links behind auth are acceptable as origin context.
- **Session note**: keep a running triage note (`.notes/`) with one section per ticket and an explicit "action left" marker per ticket, so a human can pick up the queue.

## 4. Verification tools

- Runtime loading audits and traffic simulation: [references/loading-audit.md](references/loading-audit.md).
- Production query-side checks (per-team event series, UA splits, ingestion warnings): the `query-clickhouse-via-metabase` skill covers prod-us and prod-eu access.
- Error tracking: MCP `query-error-tracking-issues-list` / `query-error-tracking-issue-events` with `verbosity: stack` gives sourcemapped frames.
