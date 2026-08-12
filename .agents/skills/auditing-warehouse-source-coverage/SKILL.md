---
name: auditing-warehouse-source-coverage
description: Audit already-implemented Data warehouse import sources for endpoints, schemas, and tables the vendor's API offers but we never wired up. Use when asked whether a source is missing endpoints, to find new endpoints a vendor has added since a source was built, to refresh COVERAGE_GAPS.md, to prioritize which source to deepen next, or to check coverage before an integration review. Covers dumping our real endpoint inventory credential-free, ranking sources by production adoption, diffing against vendor OpenAPI/GraphQL specs, and recording findings. Not for implementing a source (use implementing-warehouse-sources), adding a vendor API version (warehouse-source-new-version), or writing source docs (documenting-warehouse-sources).
---

# Auditing warehouse source endpoint coverage

Finds **endpoint gaps in sources that already work**: the vendor exposes an object users want,
and we never added a table for it.

This is the reverse of implementing a new source.
Nothing here is about the ~646 scaffolded stubs.

Output goes in
[`products/warehouse_sources/backend/temporal/data_imports/sources/COVERAGE_GAPS.md`](../../../products/warehouse_sources/backend/temporal/data_imports/sources/COVERAGE_GAPS.md).
Read it first: it records what a previous audit already found, so you extend it rather than rediscover it.

## Why this needs a method

There are ~586 implemented sources.
You cannot diff all of them against vendor docs in one pass, and a flat list of "source X has N tables"
tells you nothing, because N should be 3 for some vendors and 40 for others.

So the audit is: **establish our real inventory, rank by who actually uses it, diff the top of that
ranking by hand, and sweep the long tail with a batched workflow.**
Depth over breadth on the sources that matter; breadth via fan-out for the rest.
Ten spec-verified sources beat 200 guesses.

Both halves have been run once. `COVERAGE_GAPS.md` holds the hand-audited high-adoption sources and
`COVERAGE_GAPS_APPENDIX.md` holds the swept remainder, so a re-run is a refresh, not a cold start.

### Sweeping the long tail with a workflow

The tail is too big to audit inline but parallelizes perfectly, since sources are independent.
What worked: one `parallel()` fan-out, batches of 8 sources per agent, 69 agents for 547 sources.
It cost about 6.8M subagent tokens and 3,000 tool calls, and returned 4,540 findings with zero agent
errors, so budget accordingly before starting.
Requires explicit user opt-in to run a workflow at that scale.

Design notes that mattered:

- **Pass the payload by file, not inline.** Write `[{s, l, t, d}]` (source type, label, current tables, known docs URLs) to a scratchpad JSON, give each agent an index range, and have it read its own slice. Inlining 136KB of source data into 69 prompts is pure waste.
- **Give agents our table list up front.** It comes from `get_schemas()` and is authoritative, so agents spend their budget on vendor research instead of re-reading our code.
- **Force structured output with a schema**, including a `verified` boolean and the exact `doc_url` diffed against. That URL is what makes the result auditable afterwards.
- **Make "could not verify" an explicit, blessed answer.** Tell agents plainly that a fabricated endpoint wastes an implementer's day and is worse than reporting nothing. On the first run this held perfectly: all 542 `gaps`/`thin`/`adequate` results were `verified: true` and only the 5 genuine failures came back `could-not-verify`.

Then validate the output before trusting it:

- Bulk-check the cited `doc_url`s with `curl -o /dev/null -w "%{http_code}"`. About 95% should return 200; a low rate means agents were inventing sources.
- Spot-check a handful of findings end to end: fetch the vendor spec, confirm the claimed path exists, and confirm it is genuinely absent from our source's endpoint map.
- Expect endpoint names to hold up better than the one-line rationales beside them. Agents occasionally justify a lookup table by a field on a table we do not actually sync. Say so in the write-up rather than presenting both at equal confidence.

## Step 1: dump our real endpoint inventory

Do not read `settings.py` files by hand and do not trust `canonical_descriptions.py` alone
(it can lag the real endpoint map).
Use the registry, which reports what `get_schemas` actually returns.

Run [`scripts/dump_source_inventory.py`](scripts/dump_source_inventory.py) from the repo root:

```sh
flox activate -- bash -c "PYTHONPATH=. python .agents/skills/auditing-warehouse-source-coverage/scripts/dump_source_inventory.py > /tmp/inventory.json"
```

It leans on `Source.get_documented_tables()`, which builds a credential-free placeholder config,
so it needs no secrets and hits no vendor API.

Gotchas:

- Django logs a DEBUG-mode warning to stdout before the JSON. Strip everything before the first `{`.
- A handful of sources raise while listing (GitHub needs configured repositories, for instance). The script records the error and moves on; it does not mean the source is broken.
- `SQLSource` subclasses (Postgres, MySQL, BigQuery, Snowflake, MongoDB, Supabase, Redshift, MSSQL, ClickHouse, Neon, Convex) and file sources (Google Sheets, Custom) introspect user schemas and legitimately return nothing. Exclude them from the audit entirely; there is no fixed endpoint set to be missing.

## Step 2: rank by production adoption, not alphabetically

A gap only matters in proportion to who hits it.
Rank by distinct projects with a live connection of that source type, pulling the synced Postgres
replicas in the internal dogfood project (US project 2), which cover both regions:

```sql
SELECT source_type, count() AS connections, count(DISTINCT team_id) AS teams
FROM (
    SELECT source_type, team_id FROM postgres_posthog_externaldatasource WHERE deleted = false
    UNION ALL
    SELECT source_type, team_id FROM eu_postgres_posthog_externaldatasource WHERE deleted = false
)
GROUP BY source_type
ORDER BY teams DESC
```

Confirm column names against `system.information_schema.columns` first; the replica schema drifts.
See the `analyzing-insights-across-teams` skill for how these replicas are set up.

Then join the ranking to the inventory table counts.
The interesting signal is a **low table count with high adoption** — that is where a small amount of
work reaches the most people.

**Connection counts are internal operational data.**
Use them to prioritize, but never write them into a committed doc, PR description, or commit message.
This repo is public. Convert them to relative tiers before publishing anything.

## Step 3: diff against an authoritative vendor spec

Work down the ranking. For each source, get a machine-readable spec and diff it against our
endpoint list.

**Prefer specs over prose docs, and prefer `curl` over `WebFetch`.**
`WebFetch` summarizes with a small model and reliably drops most of an API reference; it answered
"I cannot find a list of resources" for both the Stripe and HubSpot references. Fetch the spec and
parse it yourself instead.

Specs that worked on 2026-07-26:

| Vendor     | Spec                                                                                                                 |
| ---------- | -------------------------------------------------------------------------------------------------------------------- |
| Stripe     | `https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json`                                         |
| GitHub     | `https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json` |
| Klaviyo    | `https://raw.githubusercontent.com/klaviyo/openapi/main/openapi/stable.json`                                         |
| Clerk      | `https://raw.githubusercontent.com/clerk/openapi-specs/main/bapi/2024-10-01.yml`                                     |
| Zendesk    | `https://developer.zendesk.com/zendesk/oas.yaml`                                                                     |
| Mailchimp  | `https://api.mailchimp.com/schema/3.0/Swagger.json?expand`                                                           |
| Sentry     | `https://raw.githubusercontent.com/getsentry/sentry-api-schema/main/openapi-derefed.json`                            |
| Cloudflare | `https://raw.githubusercontent.com/cloudflare/api-schemas/main/openapi.json`                                         |

For a vendor with no published spec, try in order: an `llms.txt`, a public SDK's resource modules
(client libraries enumerate every resource), the GraphQL introspection schema, then the docs sitemap.
HubSpot's `llms.txt` covers only apps and CMS, not the API reference, so it is not useful here.

Extract the resource list by pattern-matching paths that are collection `GET`s, then set-difference
against our tables. Sketch:

```python
import json, re
spec = json.load(open("spec.json"))
tops = {
    m.group(1)
    for p, ops in spec["paths"].items()
    if "get" in ops and (m := re.fullmatch(r"/v1/([a-z0-9_]+(?:/[a-z0-9_]+)?)", p))
}
```

Two things to get right:

- **Match the nesting depth the vendor uses.** A one-segment regex on GitHub misses `issues/comments` and `pulls/comments`, which are two of its most valuable endpoints. Run the extraction at one and two segments and read both.
- **Sub-resources are often the real gap.** Mailchimp's `reports/{id}/email-activity` and Klaviyo's flow messages are nested under a parent we already sync, so a top-level-only diff reports full coverage.

## Step 4: judge each gap, do not just list it

A raw set difference is noise. Most vendors have endpoints nobody wants in a warehouse.
For each missing endpoint ask:

1. **Would a user query this?** Analytical objects (transactions, events, memberships, state history, breakdowns) yes. Config and plumbing (webhook endpoints, API keys, file uploads, feature flags, OAuth apps, ephemeral tokens) usually no.
2. **Does it unlock data we already sync?** Lookup tables are the highest value-per-line work in this whole audit. HubSpot deals carry a `dealstage` ID with no `pipelines` table; Linear issues carry a state ID with no `workflow_states`. Small endpoint, large unlock. Always check for these first.
3. **Is it the vendor's headline metric?** Sentry release-health `sessions`, Zendesk `satisfaction_ratings`, Mailchimp per-recipient opens and clicks. If a vendor's own marketing leads with a number we cannot produce, that is a real gap.
4. **Is a whole product surface absent?** Cloudflare's traffic analytics, Stripe's usage-based billing, Clerk's sessions. Worth calling out as one item rather than twenty.
5. **Is it structural rather than additive?** Salesforce custom objects and Attio user-defined objects cannot be fixed by appending to an `ENDPOINTS` tuple. Flag these separately; they need design.

Also check our side for half-finished threads before writing a gap up as new work:

```sh
cd products/warehouse_sources/backend/temporal/data_imports/sources
grep -rniE "TODO|FIXME|not (yet )?(supported|implemented)" <source>/*.py | grep -vi test
```

HubSpot's `WEB_ANALYTICS_EVENTS_ENDPOINT` is defined in `settings.py` and referenced nowhere,
which makes it a cheaper item than it looks.

## Step 5: look for cross-source patterns

Before writing up, re-read your per-source findings for repeats.
Themes are more actionable than 40 separate bullets, and they change how the work gets scheduled.

Tag the findings rather than eyeballing them. Regex the `endpoint` and `why` fields of every gap into
theme buckets and count. A measured prevalence is far more persuasive to whoever schedules the work
than "this seems common", and it tells you which theme to fund first.

Patterns found so far, all still open, with their measured share of the 4,540 swept gaps:

- **Lookup tables that resolve IDs we already sync — 1,238 items, 27% of everything.** The dominant finding by a wide margin, and the cheapest to fix. We sync a record carrying a foreign key and never sync the table decoding it. Always check for this first on any source.
- Usage, billing, and cost objects (429).
- Membership and join tables materializing a many-to-many we currently drop (456).
- State and change history (424), so no time-in-state question is answerable.
- Comments, notes, and conversations attached to records we already sync (238).
- Every ad platform except LinkedIn ships no creative metadata.
- Every ad platform except Google Ads ships no breakdown dimensions (age, gender, geo, placement, device).
- Email tools ship campaign metadata but not per-recipient engagement.

When you find a new theme, add it to the patterns section of `COVERAGE_GAPS.md`.

## Step 6: record findings

Update `COVERAGE_GAPS.md` in place. Keep its conventions:

- Group by adoption tier, using relative tiers and never raw connection counts.
- Mark every source **spec-verified** (you fetched and diffed the vendor spec, with the date) or **needs confirmation** (our side read from code, vendor side from familiarity). Do not blur these. An unverified claim that an endpoint is missing wastes an implementer's time.
- Use checkboxes so items can be ticked off as they ship. Tick, do not delete, so a later audit can tell "shipped" from "never found".
- Order each source's list by value, most valuable first, and say why the top one matters.
- Keep a section on what the audit did **not** cover, so absence of a finding is never read as coverage.

## Known limits of this audit shape

State these rather than letting a reader assume otherwise:

- **Column coverage is not table coverage.** A table can exist while missing most of the vendor's fields, via sparse fieldsets, `fields[...]` params, or `properties` allowlists. That is a separate and probably larger audit than this one.
- **Existing does not mean incremental.** A table that only full-refreshes is its own class of gap and is invisible to an endpoint diff.
- **Specs are not entitlements.** An endpoint in a spec may be deprecated, plan-gated, or absent on the API version we pin. Nothing here is validated against a live vendor account.
- **Not every vendor publishes a usable spec.** Say which sources you could not verify instead of leaving them out silently.

## Related skills

- `implementing-warehouse-sources` — building a source, or adding the endpoints this audit found.
- `warehouse-source-new-version` — a vendor shipped a new API version. A version bump often adds endpoints, so it is a good trigger to re-audit that one source.
- `documenting-warehouse-sources` — the public posthog.com docs for a source, which render from `get_documented_tables()`, the same call this audit uses.
