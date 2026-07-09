---
name: documenting-warehouse-sources
description: Write or update the user-facing posthog.com documentation for a PostHog Data warehouse import source. Use when adding a new source doc, fixing an inconsistent or stub source doc, or standardizing the docs at contents/docs/cdp/sources. Covers the canonical template, shared snippets, the auto-rendered <SourceParameters /> and <SourceTables /> components, frontmatter, and the docsUrl/slug rule that prevents 404s.
---

# Documenting Data warehouse sources

User-facing source docs live in the **posthog.com** repo (not this one) at
`contents/docs/cdp/sources/<slug>.md`, served at both `/docs/cdp/sources/<slug>` and
`/docs/data-warehouse/sources/<slug>`. This skill defines the one consistent shape every source doc
must follow. Pair it with `/implementing-warehouse-sources` when shipping a new source.

Assume a sibling posthog.com checkout (e.g. `../posthog.com`).

## The two things the website renders for you

You do **not** hand-write connection fields or the table list — both come from the
`public_source_configs` API the site fetches at build time, mirrored into the doc via MDX components:

- `<SourceParameters />` renders the connection/config form fields from `get_source_config.fields`.
- `<SourceTables />` renders the **Supported tables** reference (table name, description, sync method,
  incremental field, primary key) from the source's `get_documented_tables()`.

`<SourceTables />` only has data when the source opts in by setting
`lists_tables_without_credentials = True` on its source class (only valid when `get_schemas` iterates a
**static** endpoint catalog with no I/O — see `/implementing-warehouse-sources`). Otherwise it renders a
generic "discovered from your account" note. **If a table is missing or its description is thin, fix the
source code** (`settings.py` endpoints + `canonical_descriptions.py`), not the doc — the doc just renders
what the API returns, so the code stays the single source of truth.

## Frontmatter

```yaml
---
title: Linking <Source> as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: <EnumValue> # MUST equal the ExternalDataSourceType value, e.g. ActiveCampaign, Stripe
beta: true # optional — only for beta sources
---
```

`sourceId` is what links the doc to its API config (icon, fields, tables). Get it wrong and the doc
renders with no `<SourceParameters />` / `<SourceTables />` data. It must be a real
`ExternalDataSourceType` value (PascalCase, e.g. `ActiveCampaign`, not `Active Campaign`).

## Canonical template

```text
---
title: Linking <Source> as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: <EnumValue>
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"

<!-- Alpha/beta only: import AlphaRelease from "../_snippets/alpha-release.mdx" and render <AlphaRelease /> here -->

One or two sentences: what this connector syncs and the typical use case.

## Prerequisites

Account tier / admin rights / API access the user needs before they can connect.

## Adding a data source

<SourceSetupIntro />

List the specific credentials this source needs and exactly where to get them (link to the provider's
dashboard). For sources with more than one auth method, use `###` subsections (mirror Stripe's
"Option 1 / Option 2").

## Sync modes

<SyncModes />

Add any source-specific recommendation here (e.g. "use webhooks for Stripe").

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

Source-specific errors and fixes (optional but encouraged), then:

<TroubleshootingLink />
```

### Essential sections (every source)

Status callout (alpha/beta only) → intro → Prerequisites → Adding a data source → Sync modes →
Configuration → Supported tables → Troubleshooting.

### Optional sections (when applicable)

Webhooks (real-time sync), CDC (databases), Column selection, Row filters, Inbound IP addresses
(`<InboundIpAddresses />`), data-type handling, known limitations, ERD/relationships. Reference
implementations already in the repo: **Stripe** (SaaS + webhooks), **Postgres** (database + CDC),
**ClickHouse** (database). Don't invent sections the source doesn't need.

## Shared snippets

Reuse these instead of re-writing the same prose (they live in `contents/docs/cdp/_snippets/`):

- `source-setup-intro.mdx` — the standard "Adding a data source" steps.
- `sync-modes.mdx` — sync-mode summary linking to the canonical explanation.
- `alpha-release.mdx` / `beta-release.mdx` — status callouts (also set `beta: true` in frontmatter).
- `dw-troubleshooting-link.mdx` — the troubleshooting/support footer.
- `inbound-ip-addresses.mdx` — IP allowlist table for DB sources.
- `feedback-questions.mdx` — feedback/FAQ footer.

`.md` source docs support MDX `import` (e.g. `convex.md`, `mongodb.md`), so you don't need to rename to
`.mdx` to use snippets — but `.mdx` is fine too. `CalloutBox`, `ProductScreenshot`, `SourceParameters`,
and `SourceTables` are global components — no import needed.

## docsUrl / slug rule (prevents 404s)

The website derives the doc slug from the source's `docsUrl` (its last `/docs/cdp/sources/<slug>`
segment), so these three must agree:

1. The doc **filename**: `<slug>.md`.
2. The source's `docsUrl` in `get_source_config`: `https://posthog.com/docs/cdp/sources/<slug>`.
3. (implicitly) the listing link — now derived from `docsUrl`, so it follows automatically.

Use kebab-case for multi-word slugs (`active-campaign`, not `activecampaign`). After writing or renaming
a doc, run the audit from this (posthog) repo:

```sh
python manage.py audit_source_docs --docs-dir ../posthog.com/contents/docs/cdp/sources
```

It fails if any source `docsUrl` points at a missing file or any doc's `sourceId` isn't a real source.
Renaming a published doc also needs a 301 in `posthog.com/vercel.json` for both
`/docs/cdp/sources/*` and `/docs/data-warehouse/sources/*`.

## Checklist

- [ ] Frontmatter `sourceId` matches the `ExternalDataSourceType` value exactly
- [ ] Intro, Prerequisites, Adding a data source, Sync modes, Configuration, Supported tables, Troubleshooting
- [ ] Status snippet + `beta: true` if alpha/beta
- [ ] Shared snippets used instead of bespoke prose
- [ ] `<SourceParameters />` and `<SourceTables />` present (don't hand-write fields or the table list)
- [ ] If the rendered table list is empty/thin and the source is fixed-schema, enrich its code
      (`lists_tables_without_credentials`, `settings.py`, `canonical_descriptions.py`) — see
      `/implementing-warehouse-sources`
- [ ] Filename, `docsUrl`, and slug all agree (kebab-case)
- [ ] `audit_source_docs` passes
