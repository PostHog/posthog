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
  - `deprecated_versions: tuple[VersionDeprecation, ...]` — versions the vendor has deprecated (`VersionDeprecation(version=..., sunset_at=date | None)` from `sources/common/versioning.py`).
- Each `ExternalDataSource` row pins one version in its `api_version` column (NULL resolves to `default_version`). The sync pipeline resolves the pin in `workflow_activities/import_data_sync.py` and hands it to the source as `SourceInputs.api_version` — already resolved, never None there.
- These declarations are exposed publicly via `GET /api/public_source_configs/` (`versions`, `defaultVersion`, `apiDocsUrl`, `deprecatedVersions`) and per-instance via the source API (`api_version`, `api_version_deprecation`). The `api_version` pin is queryable in HogQL via the `data_warehouse_sources` system table.
- Registry-wide invariants are enforced by `sources/tests/test_source_versions.py`: default in supported, deprecated ⊆ supported, default never deprecated, https `api_docs_url`.

## Adding a new version, step by step

1. **Read the vendor's changelog** (the source's `api_docs_url`) and list what changed between the currently supported version(s) and the new one: renamed/removed fields, changed pagination, new required headers, changed webhook payloads.
2. **Declare the version**: add the new label to `supported_versions`. Flip `default_version` to it only if new sources should start there (usually yes for stable versions). Existing pinned rows are unaffected by a default flip — that is the point of pinning.
3. **Dispatch on `SourceInputs.api_version`** at the request layer:
   - Keep it minimal. If the version is just a header/URL segment and response shapes are compatible, thread the version string down to where the client/URL is built (see Stripe: `StripeSource.source_for_pipeline` passes `self.resolve_api_version(inputs.api_version)` → `stripe_source(...)` → `StripeClient(stripe_version=...)`). Resolve through `resolve_api_version` at the source class — never hardcode a fallback version in the request layer.
   - Only introduce per-version modules/branches where behavior genuinely diverges (different pagination, different field mapping). Keep all version branching inside the source's own directory — never in shared layers.
   - Watch for version-dependent column hints/schemas: e.g. Stripe's `external_table_definitions` were built for specific versions; newer versions may need hints skipped so schemas auto-infer (grep `STRIPE_VERSIONS_WITH_EXTERNAL_TABLE_DEFINITIONS` on the open Stripe version PR for the pattern).
4. **Keep old versions working**: do not delete or alter the request path for previously supported versions. Removing a version is an explicit future decision, not part of a version-add PR.
5. **Tests**: extend the source's tests so both the old and new versions are exercised — at minimum that the version label reaches the client/request layer for each supported version (mock the boundary; parameterize over versions). The registry invariant test picks up declaration mistakes automatically.
6. **One PR per source.** Conventional title: `feat(<dir>): support <vendor> API version <label>`.

## Deprecating a version

1. Implement the newer version first (steps above) if not already supported.
2. Add the old version to `deprecated_versions` with the vendor's announced sunset date (or `sunset_at=None` if none). Never deprecate `default_version` — flip the default to the new version in the same PR.
3. The in-product warning banner and API fields light up automatically from the metadata — zero per-source UI work.
4. Include a **written-not-run** migration script that repins affected `ExternalDataSource` rows (`api_version` column) from the deprecated version to the new one, plus any safe data/schema transforms. It must be idempotent and reviewable. Where migration is lossy or unsafe, do not script it — document the manual path in the PR. Do not execute migrations or backfills; humans review and run them.

## Pinning semantics (do not break these)

- `resolve_api_version(pinned, default)` honors a present pin verbatim — even one no longer declared — because silently moving a customer to another version is the failure mode this framework prevents. Empty string / NULL fall back to the default.
- New sources are stamped with `default_version` at creation (`_create_external_data_source` in `products/data_warehouse/backend/presentation/views/external_data_source.py`).
- Repinning a customer = updating `ExternalDataSource.api_version` (support runbook: "Updating a warehouse source to a new vendor API version" in the PostHog/runbooks repo).

## Common pitfalls

- Vendor version labels are opaque: `"2026-02-25.clover"`, `"v21.0"`, `"2022-06-28"`. Copy them exactly; never normalize, sort, or parse.
- A version bump often changes **webhook payloads** too — if the source is a `WebhookSource`, check whether webhook-created clients (created at source-setup time, not sync time) also need the version and whether existing webhook subscriptions must be updated.
- Credential-validation paths (`validate_credentials`, permission probes) run at creation time with no row pin; they may use the default/legacy version. Changing them is optional per version bump — verify the vendor accepts the validation calls under the new version before switching them.
- Don't regenerate schemas for existing customers as part of a version add; schema changes only apply to rows repinned via the (human-run) migration.

## Self-improvement

After you finish a version-update or deprecation PR using this skill, **append what you learned** to the list below (vendor quirks, dispatch gotchas, test patterns). Keep entries one line each, pattern-focused, no changelog prose.

### Learnings

- (seed) Stripe: response shapes differ enough across date versions that canonical column hints must be gated per version; newer versions auto-infer schema instead.
