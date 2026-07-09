---
name: adding-inbox-sources
description: Add a new warehouse-backed source to the PostHog Code Self-driving Inbox (the feature that ships GitHub, Linear, Zendesk, pganalyze). A source syncs one warehouse table (issues/tickets/conversations) and a cloud "signals scout" watches it and emits findings. Use when asked to "add a new inbox/self-driving source", "wire up <Jira/GitLab/Sentry/Intercom/Freshdesk/Front/Gorgias/etc> as a signal source", or to extend the source-toggle grid. Covers BOTH repos (posthog/code UI wiring + posthog/posthog scout emitter) and the deploy ordering between them.
---

# Adding a Self-driving Inbox source

The Self-driving Inbox connects a PostHog **data-warehouse source** (GitHub, Linear,
Zendesk, pganalyze today), syncs one "actionable records" table (`issues` /
`tickets` / `conversations`), and a server-side **signals scout** in
`posthog/posthog` watches new rows and emits findings/reports into the Code Inbox.

**Adding a source is a two-repo change.** The scout is not generic over arbitrary
tables — it is driven by a static registry keyed on `(source_type, table)`. So you
must change both:

This skill lives in `posthog/posthog`; the UI half lives in the separate
`posthog/code` repo. Both must change:

| Repo | What changes |
| --- | --- |
| `posthog/posthog` (this repo) | New scout emitter + registry entry + `SignalSourceProduct` enum value (+ migration) + contract variant. **The data-warehouse source itself must already exist** (all Tier-1 sources do). |
| `posthog/code` | ~8 UI/wiring files: the source-product unions, toggle card, setup form, hook maps, icon, filter option (+ OAuth service/router only for OAuth sources). |

> Backend work in `posthog/posthog` should be done in a **git worktree** (see
> "Worktree setup" below). Merges in both repos go through the Trunk merge queue —
> see the `merging-prs` skill.

## Deploy ordering (do not skip)

The backend `SignalSourceProduct` choice must ship **before** the Code UI surfaces
the toggle. The Code toggle calls `createSignalSourceConfig({ source_product })`,
and the Django model rejects a `source_product` that isn't in its choices → 400.

So: **land the posthog/posthog PR(s) first (or at least the enum migration), then
the posthog/code PR.** When opening both together, note the dependency in the Code
PR description.

## The setup form: use the dynamic renderer, don't hardcode

**Do not hand-code a per-source setup form.** PostHog Cloud serves each source's
connect-form field schema over HTTP, and the app renders it generically via
`DynamicSourceSetup` (`packages/ui/src/features/inbox/components/DynamicSourceSetup.tsx`).
A new credential-based source needs **zero form code** — just route its
`DataSourceSetup` switch case to `DynamicSourceSetup` with the capitalized
`sourceType` and the `schemas` to sync.

- Endpoint: `GET /api/environments/{projectId}/external_data_sources/wizard/?source_type=<Type>` → `Record<string, SourceConfig>`. Client method: `PostHogAPIClient.getExternalDataSourceConfigs`. Hook: `useSourceConfig(sourceType)`.
- `SourceConfig.fields` is a union: `input` (text/email/password/url/number/…), `select`, `switch-group`, `oauth`, `ssh-tunnel`, `file-upload`. `DynamicSourceSetup` renders input/select/switch-group and builds the `createExternalDataSource` payload from field `name`s. The backend is the single source of truth for field names/labels/required/secret, so forms never drift.
- The field `name`s become the `payload` keys — so you no longer hand-maintain them. (Jira → `subdomain`, `email`, `api_token`; all `secret:false` except the token.)

Three cases still need bespoke handling (the generic renderer flags `oauth`/`ssh-tunnel`/`file-upload` as unsupported and disables submit):

| Case | When | Existing example |
| --- | --- | --- |
| **Generic dynamic form** | Credential inputs only (Jira, Zendesk, Freshdesk, Front, Gorgias, Sentry, GitLab). | `DynamicSourceSetup` (route the switch case to it) |
| **OAuth + integration polling** | Source authenticates via OAuth grant (Intercom `kind=intercom`); poll `getIntegrationsForProject` for the `kind`, pass `<source>_integration_id`. | `LinearSetup` |
| **Deep-link OAuth + resource picker** | User must pick a specific resource (repo/board) during setup. | `GitHubSetup` |

`ZendeskSetup`/`PgAnalyzeSetup` are the *old* hardcoded forms — leave them or
migrate them to `DynamicSourceSetup` opportunistically; don't add new ones.

Supported OAuth `kind` values (posthog `OauthIntegration.supported_kinds`,
`posthog/models/integration.py`): `slack, salesforce, hubspot, google-ads,
google-analytics, google-search-console, google-sheets, snapchat, linkedin-ads,
reddit-ads, tiktok-ads, bing-ads, meta-ads, intercom, linear, clickup, jira,
pinterest-ads, stripe` (+ `github` via App install). **A source not in this list
must use the API-key form** — its warehouse connector takes credentials directly,
independent of the OAuth integration list. (Note: even Jira's *warehouse source*
uses an API token, not the OAuth `kind=jira`.)

## Source catalog (Tier-1)

`source_type` = the capitalized DWH type string passed to `createExternalDataSource`.
Verify exact `source_type` + `payload` key names against the posthog
`external_data_sources` serializer / the source's `source.py` at implementation time.

| Product | `source_type` | Table | Auth | Setup template | `payload` keys |
| --- | --- | --- | --- | --- | --- |
| Jira | `Jira` | `issues` | API token | Zendesk | `subdomain`, `email`, `api_token` |
| GitLab | `GitLab` | `issues` | API token | Zendesk | `gitlab_host`, `personal_access_token`, `project` |
| Sentry | `Sentry` | `issues` | API token | Zendesk | `auth_token`, `organization_slug`, `api_base_url?` |
| Freshdesk | `Freshdesk` | `tickets` | API key | Zendesk | `subdomain`, `api_key` |
| Front | `Front` | `conversations` | API token | Zendesk | `api_token` |
| Gorgias | `Gorgias` | `tickets` | API key | Zendesk | `gorgias_domain`, `email`, `api_key` |
| Intercom | `Intercom` | `conversations` | OAuth (`kind=intercom`) | Linear | `intercom_integration_id` |

(Zendesk `tickets`, GitHub `issues`, Linear `issues`, pganalyze `issues`+`servers`
are already shipped — copy them, don't re-add.)

---

## posthog/code checklist (per source)

Product key is the lowercase `source_product` (e.g. `"jira"`). Grep the repo for
`"zendesk"` (case-insensitive) inside `packages/` — every hit that is
source-list-relevant is a place you must add the new product. The canonical list:

### Type gates (every source)
1. `packages/shared/src/inbox-types.ts` — add `"jira"` to the `SourceProduct` union.
2. `packages/api-client/src/posthog-client.ts` — add to `SignalSourceConfig.source_product` union; add a new `source_type` value only if the record type isn't already `issue`/`ticket`.

### Live UI path (every source)
3. `packages/ui/src/features/inbox/hooks/useSignalSourceToggles.ts` — `SetupSourceProduct`, `SOURCE_TYPE_MAP`, `SOURCE_LABELS`, `DATA_WAREHOUSE_SOURCES` (`{ dwSourceType, requiredTable }`), `ALL_SOURCE_PRODUCTS`, and the `computeValues` initializer object.
4. `packages/ui/src/features/inbox/components/SignalSourceToggles.tsx` — `SignalSourceValues` field, a `toggleX`/`setupX` callback, and a `<SignalSourceToggleCard>` in the "External connections" column (icon/label/description + `requiresSetup`/`onSetup`/`loading`/`syncStatus`).
5. `packages/ui/src/features/inbox/components/DataSourceSetup.tsx` — `DataSourceType`, `REQUIRED_SCHEMAS`, and the `switch` case. For a credential source, route the case to `<DynamicSourceSetup sourceType="Jira" title="Connect Jira" schemas={schemasPayload("jira")} … />` — **no new form component**. Only OAuth/resource-picker sources need a bespoke `XSetup`.
6. `packages/ui/src/features/inbox/components/utils/source-product-icons.tsx` — `SOURCE_PRODUCT_META` entry (`Icon`, `color`, `label`). Add an inline SVG icon file (copy `PgAnalyzeIcon.tsx`) if no Phosphor icon fits.
7. `packages/ui/src/features/inbox/filterOptions.tsx` — `INBOX_SOURCE_OPTIONS` entry (source-filter dropdown).

### Core mirror (keep in sync — `SignalSourceService`/`DataSourceService` mirror the maps; not on the live UI path today but keep them consistent)
8. `packages/core/src/inbox/signalSourceService.ts` — mirror `SOURCE_TYPE_MAP`, `DATA_WAREHOUSE_SOURCES`, `ALL_SOURCE_PRODUCTS`, `computeSourceValues` init, plus `WarehouseSourceProduct`/`SignalSourceValues`.
9. `packages/core/src/inbox/dataSourceService.ts` — `DataSourceType`, `REQUIRED_SCHEMAS`, a `createXDataSource` method.

### OAuth plumbing — **only** for OAuth sources (Intercom); API-key sources skip this
10. `packages/core/src/integrations/<source>.ts` — `XIntegrationService.startFlow(region, projectId)` (clone `linear.ts`).
11. `packages/core/src/integrations/identifiers.ts` — new `X_INTEGRATION_SERVICE` symbol.
12. `packages/core/src/integrations/integrations.module.ts` — bind it.
13. `packages/host-router/src/routers/<source>-integration.router.ts` — clone `linear-integration.router.ts`.
14. `packages/host-router/src/router.ts` — import + register the router in `appRouter`.

### Setup-form specifics
- **Credential source:** route the `DataSourceSetup` switch case to `DynamicSourceSetup` (above). Nothing else — the fields come from the wizard endpoint.
- **OAuth form:** clone `LinearSetup`. Change the `kind` matched in the poll loop and the `<source>_integration_id` payload key; swap `trpc.linearIntegration.startFlow` for the new router.
- Issues sources (`github`/`linear`/`jira`) force `issues` to `full_refresh` in `ensureRequiredTableSyncing` (`useSignalSourceToggles.ts`) — add the new product to that condition if it syncs an `issues` table (issues get edited/closed, so incremental append would miss updates). Ticket/conversation sources only force `should_sync=true`.

### Verify
- `pnpm --filter @posthog/shared build` after touching `inbox-types.ts` (it's a published type).
- `pnpm typecheck` (whole repo — the unions are consumed across packages).
- `biome lint packages/core packages/ui` — zero `noRestrictedImports`, imports ordered.

---

## posthog/posthog checklist (per source)

Scout lives in `products/signals/backend/`. The warehouse→signals handoff is
generic; only the per-source emitter + registry entry are new.

1. **Enum** — `products/signals/backend/enums.py`: add a `SignalSourceProduct` value + a `SIGNAL_SOURCE_PRODUCT_LABELS` entry. This regenerates `SIGNAL_SOURCE_PRODUCT_CHOICES` used by the model.
2. **SourceType** — `products/signals/backend/models.py` `SignalSourceConfig.SourceType`: only add if the record type isn't already `ISSUE`/`TICKET`.
3. **Migration** — `python manage.py makemigrations signals` → `NNNN_alter_signalsourceconfig_source_product`. **Batch all new enum values into ONE migration when doing several sources** — parallel PRs each adding a migration to this model collide in the merge queue.
4. **Emitter** — new module `products/signals/backend/emission/<source>_<table>.py` exporting a `SignalSourceTableConfig`: `partition_field` (incremental cursor column), `fields` (columns to SELECT), optional `where_clause`, `partition_field_is_datetime_string`, an `emitter(row) -> SignalEmitterOutput(source_product, source_type, source_id, description, weight, extra)`, and optional LLM `actionability_prompt`/`summarization_prompt`. **Copy `github_issues.py` and adapt to the warehouse table's columns** (read the source's `settings.py`/`canonical_descriptions.py` under `products/warehouse_sources/backend/temporal/data_imports/sources/<name>/` for exact column names).

   ⚠️ **Not every source stores flat columns.** GitHub/Linear expose `title`/`body`/`created_at` as top-level columns, so the generic `data_warehouse_record_fetcher` (`SELECT {fields} FROM {table} WHERE {partition_field} > cursor`) works directly. Others do **not**: e.g. **Jira's `issues` table has only `id`, `key`, `self`, `fields` (a nested JSON blob), `expand`** — `summary`/`description`/`status`/`created` all live inside `fields`. For such sources you must SELECT `fields` and `JSONExtractString(fields, '…')` in the emitter, and the `partition_field` must be a JSON expression (`JSONExtractString(fields, 'created')`, `partition_field_is_datetime_string=True`). **Verify the generic fetcher accepts a JSON-expression `partition_field`** (it interpolates it into HogQL `WHERE`) before assuming a clone works — this is the single most likely thing to be subtly wrong, and it can only be confirmed by running a sync, not by reading code. Inspect the real column shape via the source's `canonical_descriptions.py` first.
5. **Register** — `products/signals/backend/emission/registry.py` `_register_all_emitters()`: `register((ExternalDataSourceType.X, "<table>"), <config>)`.
6. **Contract** — `products/signals/backend/contracts.py`: add a `Literal[SignalSourceProduct.X]` variant.
7. The generic fetcher (`emission/fetchers/data_warehouse.py`), the gate (`emission/gate.py`), and the warehouse hook plumbing need **no** changes.

### Verify
- Migration applies cleanly; `python manage.py makemigrations --check` is clean afterward.
- The `ExternalDataSourceType` member exists in `products/warehouse_sources/backend/types.py`.

---

## Worktree setup (posthog/posthog backend work)

```bash
cd /Users/tomowers/dev/posthog/posthog
git fetch origin
git worktree add ../worktrees/inbox-<source> -b tom/inbox-<source>-source origin/master
```

Commit with signing/hooks bypassed (per global git rules):
`git -c commit.gpgsign=false commit --no-verify`. Open PRs **ready for review**
(not draft). Use semantic commit prefix `feat(data-warehouse):` for anything
touching warehouse sources / signals. Clean up the worktree when merged:
`git worktree remove ../worktrees/inbox-<source>`.

## PR conventions

- One PR per source per repo (per the request). Title: `feat(data-warehouse): add <Source> as a self-driving inbox source`.
- Base the PR body on the repo's PR template.
- Backend PRs first (or the shared enum migration first); Code PR references the backend PR and the deploy-ordering dependency.
- **Migration hygiene:** if opening several backend PRs, put all new `SignalSourceProduct` values in ONE prep PR's migration, and have the per-source emitter PRs carry no migration — otherwise they conflict.
- Follow the `merging-prs` skill to land each PR through the Trunk queue.

## Gotchas

- `source_type` (DWH, capitalized e.g. `"Jira"`) ≠ `source_product` (lowercase e.g. `"jira"`) ≠ `SourceType` record kind (`"issue"`). Three distinct fields.
- `DATA_WAREHOUSE_SOURCES` matches an existing external source by `source_type.toLowerCase()` — so `dwSourceType` must equal the real DWH type string.
- The exact `payload` keys are the real risk. They must match the posthog serializer for that `source_type`. Confirm against `source.py` before shipping.
- Keep `SOURCE_PRODUCT_META` and `INBOX_SOURCE_OPTIONS` covered for every product (the inbox `CLAUDE.md` calls this out) or findings render without an icon/filter.
- Do **not** confuse this with `packages/core/src/onboarding/githubConnectService.ts` — that's repo-access (clone/branch/PR), unrelated to warehouse sources.
