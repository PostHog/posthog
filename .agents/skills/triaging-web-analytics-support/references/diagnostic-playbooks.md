# Diagnostic playbooks by ticket shape

Worked patterns from real triage sessions, anonymized. Each playbook states the evidence chain that settles the diagnosis.

## Frontend crash

1. Get the exception: ticket usually has an exception ID or a minified stack (`chunk-XXXX.js` frames).
2. Search error tracking in the internal project (`query-error-tracking-issues-list` with `searchQuery` + a `/web` URL filter). The issue's `source` field gives the sourcemapped file; events with `verbosity: stack` give resolved function names.
3. Read the named code path. Common web analytics crash class: **kea-router JSON-parses query params**, so `?someParam=123` arrives as a number and `?p=a&p=b` as an array; any persisted reducer fed from `searchParams` can hold a non-string forever and crash every selector recompute (date change, filter change) — including on scenes that only _connect_ the logic.
4. Fix at both ends: coerce at the router boundary AND at the read path (persisted bad values outlive a boundary-only fix). Add a cheap pure-function regression test asserting non-string inputs don't throw.
5. CI gate jobs ("X Tests Pass") fail when a dependent job is cancelled by a superseded duplicate run — read the gate log before chasing phantom test failures; a runner that failed with zero executed steps is infra, rerun it.

## Two numbers don't match

Almost always scoping semantics, in one of three flavors:

- **Landing vs containing**: overview tiles scope sessions by "any event matches the filters"; per-path bounce/breakdown rows scope by session _entry_ value. Same filters, different denominators, both correct.
- **Event-level filter vs session-entry breakdown**: filtering by event `utm_campaign` selects sessions containing any matching event; the UTM breakdown tile groups by session `$entry_utm_campaign`. A session that picked up the UTM mid-session matches the filter but shows "(not set)".
- **Operator drift**: `contains` vs `equals` on URLs, path cleaning on vs off, event vs session property of the same name.

Resolution: name the two definitions precisely, then hand the customer the aligned pair (filter by the session entry property when comparing against a session-scoped breakdown). Only escalate to "bug" if the two surfaces claim the _same_ definition and still disagree.

Key code: `products/web_analytics/backend/hogql_queries/` (overview vs stats_table query builders), `posthog/hogql/database/schema/sessions_v2.py` (entry property aggregation).

## Count drop over time

The decisive question: **which layer dropped?**

1. Pull the raw daily series (`count()` on events by day for their team, via `query-clickhouse-via-metabase`). If raw counts dropped, no query-time change (bot classification, exclusions, materialization) can be the cause — those never alter stored counts.
2. Sanity checks that kill false leads fast: `$lib` + SDK version split (pinned version = no SDK regression), duplicate-UUID counts (dedup), day-of-week matched comparison (seasonality), hour-of-day spread (region/outage).
3. The bot fingerprint: only `$pageview` drops while `$pageleave` stays flat, loss concentrated in a few UA strings collapsing 10-50x week over week, ~2 pageviews/session with no pageleave. That is non-human traffic that stopped executing the JS SDK — typically the customer's edge (WAF, bot-fight mode, JS challenge) changed, or the scraper stopped. Their server logs still count those requests, which is why "our logs look unchanged".
4. Reply framing: PostHog stored what it received; identify the segment that vanished; ask what changed at their edge on the exact step dates; note the new lower level is closer to true human traffic.

## Tracker not loading / undercounting vs a competitor

Run a runtime loading audit (see [loading-audit.md](loading-audit.md)) against their live pages. Findings that recur:

- **Delivery chain beats endpoint proxying**: a reverse-proxied `api_host` is unblockable, but if the SDK loads _through GTM_, blocking `googletagmanager.com` kills it anyway. First-party script + first-party endpoint or it doesn't count.
- **Consent latency loses quick bounces**: even in banner-less regions, tag managers + consent platforms resolve asynchronously; every visitor who leaves before that window sends nothing. Measure first-request timing vs the competitor script.
- **Compare like with like**: competitor tools differ on visit definitions, bot filtering, and cookieless counting; quantify the load-chain gap before litigating definitional gaps.

## Ad-platform integration errors

- Soft-deleted sources do not block re-adding (prefix checks exclude deleted rows) — "Prefix already exists" means the old source is still live.
- OAuth reconnect failures are the top re-add blocker; Microsoft AADSTS650052 (missing tenant admin consent / service principal) surfaces as a bare `invalid_client` toast. Ask for the exact error text and _where_ it appears (sign-in popup vs field vs create toast) — each maps to a different code path.
- Account pickers may be project-admin-gated; a member sees a permission error where an admin sees accounts.
- Marketing analytics attribution: conversion events attribute via their own UTMs, else fall back to the last prior pageview carrying **both** `utm_campaign` and `utm_source` in the window, then LEFT JOIN on **exact case-sensitive campaign name** plus normalized source. Any miss lands in "organic". Zero paid conversions with a fat organic row means the join keys or the both-UTMs requirement failed, not the goals.
- Native ad sources need only their stats tables synced for spend metrics; PostHog events matter only for conversion goals.

## Channel type misclassification

- Classification is query-time (HogQL), driven by `posthog/models/channel_type/channel_definitions.json` through the `channel_definition_dict` ClickHouse dictionary; changes reclassify history automatically.
- The default decision tree ends in a fallback that maps _unknown_ source + `$direct` referring domain to Direct — an unrecognized `utm_source` on referrer-stripped traffic therefore reads as Direct. Fix by adding definition rows, not by changing the fallback (its behavior is pinned by tests as intentional for garbage UTMs).
- Definition changes need a ClickHouse migration: `add_missing_channel_types` only INSERTs missing pairs; type _changes_ need a rebuild (truncate → re-insert → `SYSTEM RELOAD DICTIONARY`). Update `create_channel_definitions_file.py` too, or the next regeneration reverts the JSON.
- Same-origin interstitials (bot challenges) destroy `document.referrer` while preserving query strings — self-referrals with intact UTMs are the signature. Mitigations: `before_send` rewrite of self-referrals, a custom channel rule on the customer's own domain, scoping the challenge down.
