---
name: warehouse-source-new-version
description: Add support for a new vendor API version to an existing Data warehouse import source, or deprecate an old one. Use when a vendor ships a new API version (Stripe date versions, Shopify quarterly versions, header-pinned revisions, /vN/ URL bumps), when implementing a version-update or deprecation task for a source under products/warehouse_sources/backend/temporal/data_imports/sources, or when repinning an ExternalDataSource to a different version. Covers deciding whether a newly announced version needs supporting at all, version declaration, dispatch, pinning semantics, deprecation metadata, and migration scripts.
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
- **A pinned source uses its version everywhere, not just at sync time.** Every vendor-touching surface on the source classes takes an `api_version: str | None = None` parameter carrying the source instance's resolved pin (`None` → `default_version`): `get_schemas`, `validate_credentials`, `get_endpoint_permissions`, and the `WebhookSource` management methods (`create_webhook`, `sync_webhook_events`, `webhook_inputs_updated`, `get_external_webhook_info`, `delete_webhook`). Callers with a source row (creation, `refresh_schemas`, background `sync_new_schemas`, webhook endpoints, schema-scoped probes) pass the resolved pin; pre-creation flows (wizard `database_schema`, one-shot `setup`) omit it, which resolves to `default_version` — the version the new row is stamped with (`get_endpoint_permissions` currently has only the pre-creation caller, so its parameter is always `None` today). Base-path/URL/header construction from it happens inside each source. Deliberately NOT version-threaded (pure mappings or version-independent surfaces — thread them if a real vendor version ever diverges there): `get_desired_webhook_events`/`webhook_resource_map` (event-name mappings), `get_connection_metadata`, and GitHub's per-repo webhook helpers in `github_warehouse_repos.py`.
- These declarations are exposed publicly via `GET /api/public_source_configs/` (`versions`, `defaultVersion`, `apiDocsUrl`, `deprecatedVersions`) and per-instance via the source API (`api_version`, `api_version_deprecation`). The `api_version` pin is queryable in HogQL via the `data_warehouse_sources` system table.
- Registry-wide invariants are enforced by `sources/tests/test_source_versions.py`: default in supported, deprecated ⊆ supported, default never deprecated, https `api_docs_url`.

## First: does the version need to exist at all?

Spotting a new vendor label is not a reason to support it. Before touching any source file, diff the new version against the one it supersedes — the source's current `default_version`, not every entry in `supported_versions` — from the vendor's docs and changelog, area by area:

- authentication — credential fields, token/header scheme, scopes, permission probes
- base URL, version header, and the paths actually served per resource
- pagination — mechanism, params, cursor semantics, page limits
- the schema list — which endpoints/tables the source exposes
- schema formats — columns, types/formats, primary keys, incremental fields
- webhook payloads and subscription registration, for a `WebhookSource`
- rate limits, error signatures, and anything else the source's request layer touches

**If none of that differs for what this source reads, don't add the version.** Leave `supported_versions` and `default_version` untouched and close the task with the per-area, changelog-cited evidence that the new label is indistinguishable from the default here. An extra label buys nothing and costs: a pin users can select, a version the tests, API, and UI carry forever, and the implied claim that the framework dispatches on it.

Add it when any of these hold:

- **any** area above diverges from that baseline, however cosmetic it looks for our reads — then branch it (step 3). Divergence from an older still-supported label doesn't count: those pins keep serving their own request path either way (step 4), so a new label that matches the default is redundant no matter how far it sits from the legacy one;
- the vendor is retiring a version rows are still pinned to, so that label stops working — adopting the new one is the point even if the wire is identical, and the retired version moves to `deprecated_versions` in the same PR;
- the source must send the label to get the behavior it already wants (a required header or URL segment), i.e. the version is a request input, not just a name.

"Nothing changed" needs the same docs evidence as a divergence. An unread changelog is not a clean diff.

## Adding a new version, step by step

1. **Read the vendor's changelog** (the source's `api_docs_url`) and list what changed between the currently supported version(s) and the new one: renamed/removed fields, changed pagination, new required headers, changed webhook payloads. Verification is docs-only — there are no stored credentials and no live-sync harness, so the docs are the sole source of truth for what each version serves. This is also the evidence the gate above runs on.
2. **Declare the version** (only once the gate says the version has to exist): add the new label to `supported_versions` and flip `default_version` to it — new sources always start on the newest stable version. A pinned row's **sync** path is unaffected by a default flip (that is the point of pinning), but two things still follow the new default: discovery/`get_schemas` if the pin isn't threaded there (step 3), and any row whose `api_version` is NULL. Reference the request layer's version constants instead of duplicating string literals.
3. **Dispatch on `SourceInputs.api_version`** at the request layer:
   - Keep it minimal. If the version is just a header/URL segment and response shapes are compatible, thread the version string down to where the client/URL is built (see Stripe: `StripeSource.source_for_pipeline` passes `self.resolve_api_version(inputs.api_version)` → `stripe_source(...)` → `StripeClient(stripe_version=...)`). Resolve through `resolve_api_version` at the source class — never hardcode a fallback version in the request layer.
   - Only introduce per-version modules/branches where behavior genuinely diverges (different pagination, different field mapping). Keep all version branching inside the source's own directory — never in shared layers.
   - When the new version renames endpoints, changes primary keys, or reshapes responses, the divergence must actually be branched — never leave the old single-version request path serving the new default. All the relevant surfaces can vary by version: `get_rows` receives the resolved pin in `inputs.api_version`; credential fields can key off `default_version`.
   - Conversely, don't add inert scaffolding: an `api_version` param no caller varies, or a version→URL map with identical values, is a review finding, not forward-compat. Declaration-only (`supported_versions`/`default_version` and nothing else) is the correct shape just when the gate above passed on a non-wire reason — the old label is being retired, or the vendor switches behavior account-side rather than per request. If the gate passed on nothing at all, there is no PR.
   - **Discovery and probe paths receive the pin — consume it.** The framework passes the resolved pin as the `api_version` parameter of `get_schemas`, `validate_credentials`, `get_endpoint_permissions`, and the webhook management methods. A multi-version source MUST build its discovery/probe/webhook clients from that parameter, not from `default_version` or a hardcoded header — otherwise a pinned source discovers/reconciles under the wrong version and its tables can disappear, duplicate, or fail reconciliation. Resolve it with `self.resolve_api_version(api_version)` — callers with a row pass an already-resolved value (mirroring `SourceInputs.api_version`), so the source-side resolve only covers pre-creation calls that pass `None`. Ignoring the parameter is only correct when you can state why the version makes no difference to that path.
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
- The API create path (`_create_external_data_source` in `products/warehouse_sources/backend/presentation/views/external_data_source.py`) stamps `default_version`, and migration `0075_backfill_externaldatasource_api_version` backfilled pre-existing rows — so most rows carry a concrete pin. But `api_version` is nullable and direct-ORM creation paths that bypass the stamping (e.g. `seed_engineering_analytics.py`, and any future seeder/backfill/script) can leave it NULL, and a NULL pin resolves to `default_version` — so it follows a flip. Don't blanket-claim "every row is pinned, so a flip is safe"; verify the actual pin state for the source, and if a NULL cohort can exist, either back it out (written-not-run migration) or confirm the versions are request-identical.
- Repinning is self-serve: the customer moves `ExternalDataSource.api_version` from the source's configuration page, or via `PATCH` on the source (also exposed as an MCP tool). It is validated against `supported_versions` and cancels in-flight syncs for the schemas that follow the source pin. The support runbook ("Updating a warehouse source to a new vendor API version" in the PostHog/runbooks repo) is now only for bulk or scripted moves.
- Creation is the one place a version cannot be chosen: new sources always start on `default_version`, and the create serializer has no `api_version` field, so a supplied one is ignored rather than honored.

## Common pitfalls

- Vendor version labels are opaque: `"2026-02-25.clover"`, `"v21.0"`, `"2022-06-28"`. Copy them exactly; never normalize, sort, or parse.
- A version bump often changes **webhook payloads** too — if the source is a `WebhookSource`, check whether webhook-created clients (created at source-setup time, not sync time) also need the version and whether existing webhook subscriptions must be updated.
- Credential-validation paths (`validate_credentials`, permission probes) run at creation time with no row pin; they may use the default/legacy version. Changing them is optional per version bump — verify the vendor accepts the validation calls under the new version before switching them.
- A passing credential probe is not evidence sync works — the probe hits one endpoint, `get_rows` hits the rest; when they diverge per version, the probe passes while every table 404s.
- Version → header/path maps must cover every supported label — a `.get()` fallthrough silently sends no version header (tracking "latest", the drift this framework prevents). Assert coverage or raise.
- Parallel version-bump PRs grab the same next migration number; the second to merge becomes a conflicting leaf and `ci:preflight` blocks it. Check `max_migration.txt` and renumber.
- Don't regenerate schemas for existing customers as part of a version add; schema changes only apply to rows repinned via the (human-run) migration.
- Discovery diffs under the SOURCE pin (`sync_new_schemas`, `refresh_schemas`, bulk sync-defaults). A schema-level `api_version` override on a version whose table set differs from the source's version can be disabled/soft-deleted by that diff — keep overrides to short verification windows, not as a long-term way to hold one table on another version.
- When a versioned source starts consuming the discovery `api_version` parameter, add the vendor's version-rejection error signature to `get_non_retryable_errors` — otherwise a retired pin turns the ~6h discovery cadence into a permanent retry/error loop with no user-facing surface.

## Self-improvement

After you finish a version-update or deprecation PR using this skill, **append what you learned** to the list below (vendor quirks, dispatch gotchas, test patterns). Keep entries one line each, pattern-focused, no changelog prose.

### Learnings

- (seed) Stripe: response shapes differ enough across date versions that canonical column hints must be gated per version; newer versions auto-infer schema instead.
- A new version label doesn't imply new paths: vendors ship a "v2" that still serves resources at `/v1/`, or replace the resource API entirely — check the docs per resource before building `/{version}/{resource}` URLs. A tell-tale in your own diff: needing a different probe/validation endpoint for the new version proves the resource sets diverge, so the sync paths need branching too.
- Grep every place the source builds a client or URL (sync, discovery, probes, error matchers, webhooks) when bumping — the ones outside the sync path silently stay on default/legacy versions.
- Simplecast: current API (api.simplecast.com + Bearer) _is_ "2.0" and the `UNVERSIONED_API_VERSION` ("v1") pin already hit it, so both labels resolve to the same live API and "2.0" shipped as a pure declaration change. That is exactly the shape the gate now skips — a renamed label over an unchanged API is not a version to support. Header-based version selection is announced but unshipped there, so if it ever ships, don't thread a speculative header ahead of the real contract (a no-op header ships risk with no present benefit).
- Two questions that resolve most "is this a real version?" calls fast: does the source send anything different on the wire, and does anything it reads come back different? Two nos and the only remaining reason to adopt the label is the old one being retired.
- Vendors rename versions for marketing (rebrands, docs-site restructures, "v2 developer platform" launches) far more often than they change the endpoints an ingest-only source reads. Diff resource by resource, not by announcement headline.
- Notion 2026-03-11: for read-only syncs a new version is often header-only — its breaking changes (`archived`->`in_trash`, `transcription`->`meeting_notes` block type, `after`->`position` on _append_ block children) only touch response fields or write paths we never call, so with an auto-inferred schema the sole dispatch is threading the resolved version into the request header. No per-version module needed.
- When the request layer hardcodes the version as a module constant (e.g. `NOTION_VERSION`), the dispatch is: add a param through the client/session builders (`notion_source` -> `get_rows` -> `_build_session` -> `_get_headers`), pass `self.resolve_api_version(inputs.api_version)` from `source_for_pipeline`, and give the standalone `validate_credentials(token, api_version)` `self.default_version` (creation-time, version-agnostic probe).
- Test pattern that stayed cheap: parameterize the header builder over supported versions (header carries requested version) + mock `notion_source` in the source module and assert `call_args.kwargs["api_version"]` for none/legacy/new pins (resolution + threading in one).
- Auto-inferred-schema sources (`has_managed_hogql_schema=False`) turn new attributes into new columns automatically, so a version bump whose breaking changes only touch fields the source never reads needs no data/schema transform — the repin migration is a plain idempotent `api_version` UPDATE. Verify field-by-field against the changelog instead of assuming a date bump is breaking.
- A repin migration's reverse must be a no-op: after repinning, rows on the new default are indistinguishable from natively-created ones, so a blanket downgrade would clobber legitimate native pins (same reasoning as the 0075 api_version backfill).
- A version bump can change the _auth scheme_, not just the wire format (Greenhouse Harvest v3 drops HTTP Basic API keys for OAuth2 client-credentials Bearer JWTs). Then the source config needs both credential shapes as optional fields, `_build_auth(api_version, ...)` picks one, and `validate_credentials` enforces the pair the resolved version needs — form-level `required` can't express "depends on the pin".
- When the new version's credentials can't be derived from the old ones, there is no repin migration to write: an `api_version` UPDATE would point existing rows at credentials they don't have. Ship the `deprecated_versions` banner and document the manual re-credential path instead.
- Keep the schema/table name set identical across versions even when the vendor renames a collection (Harvest `scheduled_interviews` -> v3 `interviews`): put the rename in a per-version path on the endpoint config, so discovery diffs can't orphan a table on repin.
- Vendor OpenAPI is often embedded in the docs pages themselves (`/reference/get_v3-<resource>.md`, indexed by `llms.txt`) — parse it to confirm paths, filter params, response envelope, and id types for all endpoints at once instead of trusting a prose migration guide.
