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

1. **Read the vendor's changelog** (the source's `api_docs_url`) and list what changed between the currently supported version(s) and the new one: renamed/removed fields, changed pagination, new required headers, changed webhook payloads. Verification is docs-only — there are no stored credentials and no live-sync harness, so the docs are the sole source of truth for what each version serves.
2. **Declare the version**: add the new label to `supported_versions` and flip `default_version` to it — new sources always start on the newest stable version. A pinned row's **sync** path is unaffected by a default flip (that is the point of pinning), but two things still follow the new default: discovery/`get_schemas` if the pin isn't threaded there (step 3), and any row whose `api_version` is NULL. Reference the request layer's version constants instead of duplicating string literals.
3. **Dispatch on `SourceInputs.api_version`** at the request layer:
   - Keep it minimal. If the version is just a header/URL segment and response shapes are compatible, thread the version string down to where the client/URL is built (see Stripe: `StripeSource.source_for_pipeline` passes `self.resolve_api_version(inputs.api_version)` → `stripe_source(...)` → `StripeClient(stripe_version=...)`). Resolve through `resolve_api_version` at the source class — never hardcode a fallback version in the request layer.
   - Only introduce per-version modules/branches where behavior genuinely diverges (different pagination, different field mapping). Keep all version branching inside the source's own directory — never in shared layers.
   - When the new version renames endpoints, changes primary keys, or reshapes responses, the divergence must actually be branched — never leave the old single-version request path serving the new default. All the relevant surfaces can vary by version: `get_rows` receives the resolved pin in `inputs.api_version`; credential fields can key off `default_version`.
   - Conversely, don't add inert scaffolding: if the vendor doesn't version via a header/URL segment, declaring `supported_versions`/`default_version` is the whole change — an `api_version` param no caller varies, or a version→URL map with identical values, is a review finding, not forward-compat.
   - **Discovery and probe paths do NOT inherit the sync pin.** `get_schemas` (called from `sync_new_schemas.py` without the version), OAuth account listing, and permission probes build their own client and default to `default_version` or a legacy header. If response shapes differ across versions, an existing pinned source discovers/reconciles under the new default and its tables can disappear, duplicate, or fail reconciliation. So for any multi-version source you MUST thread the resolved pin into these paths (the source pin is in scope at the `sync_new_schemas.py` call site) — not "can", must — unless you can state why the version makes no difference to discovery.
   - Watch for version-dependent column hints/schemas: e.g. Stripe's `external_table_definitions` were built for specific versions. When adding a version whose response shapes differ, gate the canonical column hints to the versions they were built for and let newer versions auto-infer the schema from the data (a set of hint-compatible versions checked where hints are applied). For `has_managed_hogql_schema=True` sources this includes the read path: `hogql_definition`'s canonical column mapping is version-blind, so renamed columns need the canonical schema/descriptions updated too.
4. **Keep old versions working**: do not delete or alter the request path for previously supported versions. Removing a version is an explicit future decision, not part of a version-add PR.
5. **Tests**: extend the source's tests so both the old and new versions are exercised — at minimum that the version label reaches the client/request layer for each supported version (mock the boundary; parameterize over versions). The registry invariant test picks up declaration mistakes automatically. Don't re-test the base-class `resolve_api_version` contract (`test_source_versions.py` covers every source). When versions diverge, shape fixtures per version from the vendor docs — a v1-shaped mock under a v2 pin proves nothing.
6. **One PR per source.** Conventional title: `feat(warehouse_sources): support <vendor> API version <label>` — the scope is always `warehouse_sources` (the product), never the source dir/vendor name.

## Deprecating a version

1. Implement the newer version first (steps above) if not already supported.
2. Add the old version to `deprecated_versions` with the vendor's announced sunset date (or `sunset_at=None` if none). Never deprecate `default_version` — flip the default to the new version in the same PR.
3. The in-product warning banner and API fields light up automatically from the metadata — zero per-source UI work.
4. Include a **written-not-run** migration script that repins affected `ExternalDataSource` rows (`api_version` column) from the deprecated version to the new one, plus any safe data/schema transforms. It must be idempotent and reviewable. Where migration is lossy or unsafe, do not script it — document the manual path in the PR. Do not execute migrations or backfills; humans review and run them.
5. **Never touch `ExternalDataSchema.api_version` overrides** in migration scripts — they are user-managed by design. The schema-level deprecation warning covers them; the user migrates them from the schema's configuration page.

## Pinning semantics (do not break these)

- `source.resolve_api_version(pinned)` honors a present pin verbatim — even one no longer declared — because silently moving a customer to another version is the failure mode this framework prevents. Empty string / NULL fall back to the source class's own `default_version`.
- The API create path (`_create_external_data_source` in `products/data_warehouse/backend/presentation/views/external_data_source.py`) stamps `default_version`, and migration `0075_backfill_externaldatasource_api_version` backfilled pre-existing rows — so most rows carry a concrete pin. But `api_version` is nullable and direct-ORM creation paths that bypass the stamping (e.g. `seed_engineering_analytics.py`, and any future seeder/backfill/script) can leave it NULL, and a NULL pin resolves to `default_version` — so it follows a flip. Don't blanket-claim "every row is pinned, so a flip is safe"; verify the actual pin state for the source, and if a NULL cohort can exist, either back it out (written-not-run migration) or confirm the versions are request-identical.
- Repinning a customer = updating `ExternalDataSource.api_version` (support runbook: "Updating a warehouse source to a new vendor API version" in the PostHog/runbooks repo).

## Common pitfalls

- Vendor version labels are opaque: `"2026-02-25.clover"`, `"v21.0"`, `"2022-06-28"`. Copy them exactly; never normalize, sort, or parse.
- A version bump often changes **webhook payloads** too — if the source is a `WebhookSource`, check whether webhook-created clients (created at source-setup time, not sync time) also need the version and whether existing webhook subscriptions must be updated.
- Credential-validation paths (`validate_credentials`, permission probes) run at creation time with no row pin; they may use the default/legacy version. Changing them is optional per version bump — verify the vendor accepts the validation calls under the new version before switching them.
- A passing credential probe is not evidence sync works — the probe hits one endpoint, `get_rows` hits the rest; when they diverge per version, the probe passes while every table 404s.
- Version → header/path maps must cover every supported label — a `.get()` fallthrough silently sends no version header (tracking "latest", the drift this framework prevents). Assert coverage or raise.
- Parallel version-bump PRs grab the same next migration number; the second to merge becomes a conflicting leaf and `ci:preflight` blocks it. Check `max_migration.txt` and renumber.
- Don't regenerate schemas for existing customers as part of a version add; schema changes only apply to rows repinned via the (human-run) migration.

## Self-improvement

After you finish a version-update or deprecation PR using this skill, **append what you learned** to the list below (vendor quirks, dispatch gotchas, test patterns). Keep entries one line each, pattern-focused, no changelog prose.

### Learnings

- (seed) Stripe: response shapes differ enough across date versions that canonical column hints must be gated per version; newer versions auto-infer schema instead.
- A new version label doesn't imply new paths: vendors ship a "v2" that still serves resources at `/v1/`, or replace the resource API entirely — check the docs per resource before building `/{version}/{resource}` URLs. A tell-tale in your own diff: needing a different probe/validation endpoint for the new version proves the resource sets diverge, so the sync paths need branching too.
- Grep every place the source builds a client or URL (sync, discovery, probes, error matchers, webhooks) when bumping — the ones outside the sync path silently stay on default/legacy versions.
- Simplecast: current API (api.simplecast.com + Bearer) _is_ "2.0" and the `UNVERSIONED_API_VERSION` ("v1") pin already hit it, so both labels resolve to the same live API — adding "2.0" as the new default is a pure declaration change with no wire divergence. Header-based version selection is announced but unshipped, so don't thread a speculative version header onto requests: declare `supported_versions`/`default_version` now and defer the wire dispatch until the real header contract exists (a no-op header ships risk with no present benefit).
- Salesforce: version is just the `/services/data/<version>/query` URL segment — thread the resolved string into `get_resource`/`salesforce_source` and build the path with an f-string; SOQL, pagination and response shapes are identical across v61→v67 so no per-version branching or column-hint gating needed.
