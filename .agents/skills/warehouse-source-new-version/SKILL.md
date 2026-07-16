---
name: warehouse-source-new-version
description: Add support for a new vendor API version to an existing Data warehouse import source, or deprecate an old one. Use when a vendor ships a new API version (Stripe date versions, Shopify quarterly versions, header-pinned revisions, /vN/ URL bumps), when implementing a version-update or deprecation task for a source under products/warehouse_sources/backend/temporal/data_imports/sources, or when repinning an ExternalDataSource to a different version. Covers version declaration, dispatch, pinning semantics, deprecation metadata, and migration scripts.
---

# Adding a new vendor API version to a warehouse source

Use this skill when a vendor has released a new API version and an existing source under
`products/warehouse_sources/backend/temporal/data_imports/sources/<dir>/` must support it
**while keeping every previously supported version functional**.

## How versioning works

- Every source class (subclass of `_BaseSource` in `sources/common/base.py`) declares:
  - `supported_versions: tuple[str, ...]` — opaque vendor labels, never parsed or ordered by the framework. Default `("v1",)` (`UNVERSIONED_API_VERSION`) for vendors without meaningful versioning.
  - `default_version: str` — used when a source instance has no pin, and stamped onto newly created sources.
  - `api_docs_url: str | None` — the vendor's API docs/changelog page (where new versions are announced). Distinct from `docsUrl` (posthog.com).
  - `deprecated_versions: tuple[VersionDeprecation, ...]` — versions the vendor has deprecated (`VersionDeprecation(version=..., sunset_at=date | None)` from `sources/common/base.py`).
- Each `ExternalDataSource` row pins one version in its `api_version` column (NULL resolves to `default_version`). A schema may additionally carry a user-managed override in `ExternalDataSchema.api_version` (set from the schema's configuration page; not available for webhook-sync schemas) which wins over the source pin for that schema only. The sync pipeline resolves override → pin → default in `workflow_activities/import_data_sync.py` and hands the result to the source as `SourceInputs.api_version` — already resolved, never None there.
- These declarations are exposed publicly via `GET /api/public_source_configs/` (`versions`, `defaultVersion`, `apiDocsUrl`, `deprecatedVersions`) and per-instance via the source API (`api_version`, `api_version_deprecation`). The `api_version` pin is queryable in HogQL via the `data_warehouse_sources` system table.
- Registry-wide invariants are enforced by `sources/tests/test_source_versions.py`: default in supported, deprecated ⊆ supported, default never deprecated, https `api_docs_url`.

## Adding a new version, step by step

1. **Read the vendor's changelog** (the source's `api_docs_url`) and list what changed between the currently supported version(s) and the new one: renamed/removed fields, changed pagination, new required headers, changed webhook payloads.
2. **Declare the version**: add the new label to `supported_versions`. Reference the same module-level version constants the request layer uses — don't hardcode string literals here that duplicate `<vendor>.py` constants (two sources of truth drift). Flip `default_version` to it only if new sources should start there (usually yes for stable versions). Existing pinned rows are unaffected by a default flip — that is the point of pinning.
   - **Before flipping the default, confirm the new version serves the same resource paths and response envelope the source already reads.** A default flip sends every _new_ source to the new version at sync time; if that version 404s or reshapes responses, new-source creation is broken end-to-end while mocked tests stay green. This is the single most common way these PRs break. If the vendor's new version is a full resource-API replacement (different endpoint paths, different primary keys, different auth) rather than a header/URL-segment reskin, it **cannot be expressed with the shared endpoint catalog yet** — add the label but keep `default_version` on the old version (or don't add it) until `get_rows`, `get_schemas`, and the credential fields can vary per version. Tell-tale sign in your own diff: you had to change the probe/validation path to a _different endpoint_ for the new version — that proves the resource sets differ.
   - **Run one live sync (or credential-less real request) against the new version before flipping the default.** Mocked tests only prove the code assembles a URL/header — never that the vendor serves it. State in the PR that you did this, or keep the old default.
3. **Dispatch on `SourceInputs.api_version`** at the request layer:
   - Keep it minimal. If the version is just a header/URL segment and response shapes are compatible, thread the version string down to where the client/URL is built (see Stripe: `StripeSource.source_for_pipeline` passes `self.resolve_api_version(inputs.api_version)` → `stripe_source(...)` → `StripeClient(stripe_version=...)`). Resolve through `resolve_api_version` at the source class — never hardcode a fallback version in the request layer.
   - Only introduce per-version modules/branches where behavior genuinely diverges (different pagination, different field mapping). Keep all version branching inside the source's own directory — never in shared layers.
   - **Don't add inert scaffolding.** If the vendor doesn't version via a header or URL segment (e.g. versions differ only by region subdomain, or both labels map to the same host/path), threading `api_version` through the request layer changes no request — it's an unused param and a host/path map that maps every label to the same value. In that case declaring `supported_versions`/`default_version` is the whole change; stop there. An `api_version` parameter that no caller varies, or a `_base_url_by_version` dict with identical values, is a review finding, not forward-compat.
   - **Thread the version into the discovery and probe paths too, or decide deliberately not to.** `get_schemas`/schema reconciliation and OAuth account-listing/credential probes often build their own client and silently use `default_version` or a hardcoded legacy header. After a default flip that means discovery runs against a _different_ version than the pinned sync, and a legacy probe header can be the _oldest_ declared version — due to sunset first. Either thread the resolved pin (or the current default) into these paths, or note explicitly why the legacy version is safe there.
   - Watch for version-dependent column hints/schemas: e.g. Stripe's `external_table_definitions` were built for specific versions. When adding a version whose response shapes differ, gate the canonical column hints to the versions they were built for and let newer versions auto-infer the schema from the data (a set of hint-compatible versions checked where hints are applied).
   - **Gate the _read_ path, not just the write path, for managed-schema sources.** For sources with `has_managed_hogql_schema=True`, `WarehouseTable.hogql_definition` unconditionally applies the canonical column mapping from `external_tables[...]` (and `canonical_descriptions.py`) with no `api_version` awareness. Gating write-side `column_hints` per version is not enough: a new-version source still gets exposed through the old version's canonical column mapping, so any renamed/removed/retyped canonical column reads null or fails at query time. When the new version renames columns (e.g. Notion `archived` → `in_trash`), update the canonical schema/descriptions or confirm the mapping still resolves.
4. **Keep old versions working**: do not delete or alter the request path for previously supported versions. Removing a version is an explicit future decision, not part of a version-add PR.
5. **Tests**: extend the source's tests so both the old and new versions are exercised — at minimum that the version label reaches the client/request layer for each supported version (mock the boundary; parameterize over versions). The registry invariant test picks up declaration mistakes automatically.
   - Don't re-test the generic base-class `resolve_api_version` behavior — `tests/test_source_versions.py` already asserts it for every source. A test that only checks `resolve_api_version(None) == default_version` is a change-detector; the source-specific test must assert the version reaches the actual URL/header.
   - A mocked test that feeds a _v1-shaped_ response to a _v2_ pin proves nothing about v2 — it can't catch a 404 or a reshaped envelope. When versions diverge, assert the divergent path/shape, and lean on the live-sync check above for the rest.
6. **One PR per source.** Conventional title: `feat(warehouse_sources): support <vendor> API version <label>` — the scope is always `warehouse_sources` (the product), never the source dir/vendor name.

## Deprecating a version

1. Implement the newer version first (steps above) if not already supported.
2. Add the old version to `deprecated_versions` with the vendor's announced sunset date (or `sunset_at=None` if none). Never deprecate `default_version` — flip the default to the new version in the same PR.
3. The in-product warning banner and API fields light up automatically from the metadata — zero per-source UI work.
4. Include a **written-not-run** migration script that repins affected `ExternalDataSource` rows (`api_version` column) from the deprecated version to the new one, plus any safe data/schema transforms. It must be idempotent and reviewable. Where migration is lossy or unsafe, do not script it — document the manual path in the PR. Do not execute migrations or backfills; humans review and run them.
5. **Never touch `ExternalDataSchema.api_version` overrides** in migration scripts — they are user-managed by design. The schema-level deprecation warning covers them; the user migrates them from the schema's configuration page.

## Pinning semantics (do not break these)

- `source.resolve_api_version(pinned)` honors a present pin verbatim — even one no longer declared — because silently moving a customer to another version is the failure mode this framework prevents. Empty string / NULL fall back to the source class's own `default_version`.
- New sources are stamped with `default_version` at creation (`_create_external_data_source` in `products/data_warehouse/backend/presentation/views/external_data_source.py` — `api_version=source.default_version` on `ExternalDataSource.objects.create(...)`), and pre-existing rows were backfilled by migration `0075_backfill_externaldatasource_api_version` (`API_VERSION_BY_SOURCE_TYPE`, else `DEFAULT_API_VERSION`). So an existing source's `api_version` is a concrete pin, **not NULL** — do not justify a default flip in the PR with "unpinned/NULL rows are unaffected"; that premise is false and has shipped in more than one PR. State the real reason: existing rows carry a pin (verify which one via the backfill map + creation stamp), and a default flip only changes newly created sources.
- Repinning a customer = updating `ExternalDataSource.api_version` (support runbook: "Updating a warehouse source to a new vendor API version" in the PostHog/runbooks repo).

## Common pitfalls

- Vendor version labels are opaque: `"2026-02-25.clover"`, `"v21.0"`, `"2022-06-28"`. Copy them exactly; never normalize, sort, or parse.
- A version bump often changes **webhook payloads** too — if the source is a `WebhookSource`, check whether webhook-created clients (created at source-setup time, not sync time) also need the version and whether existing webhook subscriptions must be updated.
- Credential-validation paths (`validate_credentials`, permission probes) run at creation time with no row pin; they may use the default/legacy version. Changing them is optional per version bump — verify the vendor accepts the validation calls under the new version before switching them.
- **A passing credential probe does not mean sync works under the new version.** The probe hits one endpoint; `get_rows` hits the resource endpoints. If those diverge across versions, the probe can pass (false green) while every table 404s. Don't treat "validation succeeded" as evidence the new default is functional.
- **Guard version → header/path maps against unmapped labels.** `HEADERS.get(api_version)` returning `None` for a label you forgot to add sends _no_ version header — silently tracking "latest", the exact drift the framework exists to prevent. Assert the map covers `supported_versions`, or raise on a missing non-legacy label instead of falling through.
- **Check `max_migration.txt` for a numbering collision.** When you write a repin migration, several parallel version-bump PRs may all grab the same next number (`0079`). Whichever merges second becomes a conflicting leaf migration and `ci:preflight` blocks it — sequence the merges and renumber to land after the sibling.
- Don't regenerate schemas for existing customers as part of a version add; schema changes only apply to rows repinned via the (human-run) migration.

## Self-improvement

After you finish a version-update or deprecation PR using this skill, **append what you learned** to the list below (vendor quirks, dispatch gotchas, test patterns). Keep entries one line each, pattern-focused, no changelog prose.

### Learnings

- (seed) Stripe: response shapes differ enough across date versions that canonical column hints must be gated per version; newer versions auto-infer schema instead.
- ShipStation v1→v2 (ShipEngine) is a full resource-API replacement — different endpoint paths + primary keys, not a reskin; the shared endpoint catalog can't serve v2, so a default flip 404s every new-source table while the `/carriers` probe passes green. Don't add such a version as default.
- Kustomer: vendor "v2" docs still serve the listed resources at `/v1/` paths — building `/v2/<resource>` from a v2 pin 404s. Verify the new version actually serves each resource path before flipping the default.
- Omnisend: dated versions (`2026-03-15`) reshape several list resources into event-centric endpoints; keeping the `/v3` list envelope assumption `KeyError`s on `data[config.data_key]`. Repo note said "verify against the live API before changing endpoint behavior" — heed it.
- Stripe dahlia: gating write-side `column_hints` per version isn't enough for managed-schema sources — `hogql_definition` still forces the acacia canonical column mapping on the read path regardless of pin.
- LinkedIn Ads: the OAuth account-listing client was left on the oldest declared header (`202508`), which sunsets first — advancing the sync version but not the listing version breaks new-source setup later.
- Google Ads: `get_schemas`/discovery hardcoded `self.default_version`, so a pinned older source discovers schemas against the new default. Thread the pin into discovery.
- Recurring: PRs justified safety with "existing unpinned (NULL) rows unaffected" — false, rows are pinned via creation-stamp + backfill `0075`. And most of these bumps thread a version that changes no request (inert scaffolding) — declare-only would have sufficed.
