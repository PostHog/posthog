# IDOR test coverage — audit + roadmap (2026 Q2)

This document is **self-contained**. A fresh agent (or human) without
prior context can read it, understand the current state of the
auto-IDOR framework, and execute every remaining work item.

It supersedes `COVERAGE_GAPS_PLAN.md` (most of which has shipped). The
older doc is retained for the historical methodology notes.

## TL;DR

The IDOR framework auto-generates parametric tests over every
tenant-scoped DRF viewset registered under `/api/`. It currently runs
**7 parametrics** producing **750+ test cases**, with explicit-skip
documentation for everything not auto-tested.

Run locally:

```bash
hogli test posthog/test/test_idor_coverage.py
python -m pytest posthog/test/idor/                         # framework unit tests (no DB)
python .github/scripts/check-idor-test-coverage.py          # CI gate
python .github/scripts/check-idor-test-coverage.py --update-snapshot  # refresh after un-skipping
```

**Current numbers (master + branch `tom/auto-idor-check`):**

| Layer                            | Cases | What it catches                                    |
| -------------------------------- | ----- | -------------------------------------------------- |
| `test_cross_team_get_detail`     | 131   | queryset scoping on GET (info disclosure)          |
| `test_cross_team_patch_detail`   | 131   | queryset scoping on PATCH (cross-tenant mutation)  |
| `test_cross_team_delete_detail`  | 131   | queryset scoping on DELETE (cross-tenant deletion) |
| `test_cross_tenant_fk_in_patch`  | ~32   | victim FK pk smuggled into PATCH body              |
| `test_cross_tenant_fk_in_post`   | ~32   | victim FK pk smuggled into CREATE body             |
| `test_cross_tenant_id_in_action` | 6     | victim id smuggled into custom @action body        |
| `test_cross_org_root_access`     | 5     | direct attack on victim's tenant root URL          |

**Coverage tally:**

| Metric                                       | Count               |
| -------------------------------------------- | ------------------- |
| Tenant-scoped viewsets in router             | 210                 |
| Auto-tested via standard parametrics         | 131                 |
| Tenant-root tested                           | 5                   |
| Explicitly skipped (documented)              | 20                  |
| **Viewsets in some IDOR test**               | **156 / 210 (74%)** |
| Writable tenant-FK fields covered            | 66                  |
| `@action` endpoints (total)                  | 627                 |
| ↳ with introspectable request body           | 57                  |
| ↳ without (no `@extend_schema(request=...)`) | 64                  |

**Remaining 20 explicit skips:**

- `LEGACY_FLAT_URL` (8) — slated for removal
- `NO_MODEL` (10) — wrap ClickHouse / external services
- `CUSTOM_LOOKUP_FIELD` (1) — `OrganizationFeatureFlagView` (no model + string-key lookup)
- `RETURNS_200_WITH_EMPTY_AGGREGATION` (1) — `AppMetricsViewSet` (1-line viewset bug)

---

## Architecture (file map)

```text
posthog/test/idor/
├── COVERAGE_PLAN_2026Q2.md      # ← this file
├── COVERAGE_GAPS_PLAN.md        # historical (most items shipped)
├── PHASE_5A_REGRESSION.md       # regression methodology
├── PHASE_5B_CREATE_PLAN.md      # POST coverage (shipped)
├── PHASE_5C_NAME_PATTERN_PLAN.md # @action coverage (shipped)
├── MANY_RELATED_PLAN.md         # M2M coverage (shipped)
│
├── __init__.py                  # public exports
├── discovery.py                 # walk router.urls; emit IDORTestCase per tenant-scoped viewset
├── url_structure.py             # parse DRF URL regex; build_url / build_list_url / build_action_url
├── factory.py                   # build_minimal_instance + sentinel embedding
├── fixtures.py                  # per-model factory registry (~30 entries)
├── body_factory.py              # build_minimal_post_body — DRF introspection + per-serializer registry
├── post_body_fixtures.py        # body fixture registry (per Serializer class)
├── fk_target_models.py          # parses .semgrep/rules/idor-team-scoped-models.yaml
├── fk_discovery.py              # discover_writable_tenant_fks + discover_action_serializers
├── tenant_root.py               # 5 explicit cross-org root viewset registrations
├── skip_list.py                 # 5 skip lists (TEST / FK_PATCH / FK_POST / ACTION / 5XX_LATENT)
├── mixin.py                     # IDORTestMixin (victim org/team/user + assertions)
├── _coverage_snapshot.json      # CI gate snapshot (FK pairs + action pairs)
├── test_*.py                    # ~120 unit tests (no DB required)

posthog/test/test_idor_coverage.py            # the parametric test class (DB-required)
.github/scripts/check-idor-test-coverage.py   # CI gate; --update-snapshot regenerates the snapshot
.github/workflows/ci-backend.yml              # runs unit tests in repo-checks; full sweep in django job
.semgrep/rules/idor-team-scoped-models.yaml   # tenant-scoped model allowlist (source of truth)
.agents/security.md                           # public docs
```

### FK detection layers (`fk_discovery.py::_classify_field`)

1. `ManyRelatedField` (PK with `many=True`) — uses `child_relation`
2. `PrimaryKeyRelatedField` — explicit FK; `queryset.model` resolves target. For Meta.read_only_fields-injected fields with no queryset, falls back to `serializer_model._meta.get_field` to resolve.
3. `ListField(child=Integer/UUID/Char)` named `<thing>_ids` — bulk-id pattern, emits `is_many=True`
4. **Implicit string-id on `ModelSerializer`** — `<thing>_id = IntegerField()` where `Meta.model._meta.get_field('<thing>')` is a `ForeignKey`
5. **Name-pattern fallback** (any Serializer) — `<thing>_id` / `<thing>_key` / `<thing>_short_id` mapped to tenant-scoped model names by suffix match. Carries `lookup_attr` so runtime reads `victim.pk` / `victim.key` / `victim.short_id`. Ambiguous matches emit one record per candidate.
6. **Recursion**: walks nested `Serializer` subclasses (both ModelSerializer and plain) up to `MAX_NESTING = 3` with cycle detection (`visited` set on serializer types).

### Action discovery (`fk_discovery.py::discover_action_serializers`)

Walks `viewset.get_extra_actions()`, pulls the request serializer from
`@extend_schema(request=...)` (drf-spectacular) via closure
introspection — the captured `request` value lives in
`ExtendedSchema.get_request_serializer.__code__.co_freevars` /
`__closure__`. Returns `ActionSerializerCase` carrying method_name,
url_path, http_methods, detail flag, and serializer_cls.

### Test mixin (`mixin.py::IDORTestMixin`)

`setUpTestData` creates `victim_org`, `victim_project`, `victim_team`,
`victim_user` alongside the `APIBaseTest` defaults. The attacker is
`self.user` in `self.team`/`self.organization`/`self.project`.

Assertions:

- `assertCrossTeamDenied(url, method, data)` — calls the URL as the
  attacker, raises if status is 2xx, returns the response.
- `assertSentinelNotLeaked(response, sentinel)` — substring check on
  the decoded response body; raises on hit.
- `assertCrossOrgDenied(...)` — alias of `assertCrossTeamDenied`
  (same shape, different semantic name for tenant-root tests).

### Sentinel mechanism (`factory.py`)

`reset_sentinel()` returns a fresh `idor-sentinel-<12hex>` per call.
`build_minimal_instance` embeds the **current** sentinel into string
fields when auto-creating a victim resource. The sentinel must be
generated _before_ the victim is built and _after_ the attacker is
built so leak detection only fires on victim data.

### Coverage snapshot (`_coverage_snapshot.json`)

CI gate enumerates `(viewset, FK)` and `(viewset, action)` pairs and
fails when a new pair is not in the snapshot. Refresh with
`--update-snapshot` after auditing changes. The snapshot prevents new
viewsets from silently slipping past the parametric.

---

## Conventions

### Skip-list philosophy

5 skip lists in `skip_list.py`:

| List                      | Purpose                                       | Currently       |
| ------------------------- | --------------------------------------------- | --------------- |
| `IDOR_TEST_SKIP_LIST`     | Viewset can't be auto-tested at all           | 20 entries      |
| `IDOR_FK_PATCH_SKIP_LIST` | Skip the PATCH-FK parametric for this viewset | 0               |
| `IDOR_FK_POST_SKIP_LIST`  | Skip the POST-FK parametric for this viewset  | 1 (EdgeViewSet) |
| `IDOR_ACTION_SKIP_LIST`   | Skip a specific (viewset, @action)            | 0               |
| `IDOR_5XX_KNOWN_LATENT`   | Suppress the 5xx warning for known cases      | 0               |

Every entry needs a documented category + reason. Categories include
`LEGACY_FLAT_URL`, `NO_MODEL`, `CUSTOM_LOOKUP_FIELD`,
`TENANT_ROOT_RESOURCE` (now empty — covered by tenant_root parametric),
`LATENT_ERROR_HANDLING_BUG`, `BODY_SYNTHESIS_INFEASIBLE`,
`INTENTIONAL_CROSS_TENANT`, `POST_NOT_ALLOWED`, etc.

The CI gate fails on stale entries (skip references a viewset that no
longer exists).

### Discovery filter (`discovery.py`)

A viewset becomes an `IDORTestCase` when:

1. It subclasses `TeamAndOrgViewSetMixin`.
2. It has at least one URL whose final kwarg matches the viewset's
   `lookup_field` / `lookup_url_kwarg` (rejects custom-action
   sub-resource URLs).
3. The model is resolvable from `queryset.model` or
   `serializer_class.Meta.model`.
4. The URL kwarg corresponds to a readable attribute on the model
   (`pk` / `id` always; otherwise validated via
   `_model_has_lookup_attr`, which traverses `__` for joined attrs).

### Runtime URL construction

`URLStructure.build_url(root_id, pk, intermediate_ids)` produces
`/api/<root>/<root_id>/<intermediate>/<id>/<resource>/<pk>/`. The
runtime test reads the lookup value via `_read_lookup_value(instance,
case.url.pk_kwarg)` which walks `__` chains (`instance.user.uuid` for
`user__uuid`).

---

## Coverage gaps — what's NOT tested today

Each gap below is an actionable work item with: (a) what's missing, (b)
why it matters, (c) one or more concrete examples, (d) implementation
approach with file/function references, (e) effort estimate, (f) how to
verify the change works.

### Tier 1 — high impact, low/medium effort

#### A3. PUT (full update) on detail URLs

**Missing.** 125 viewsets accept PUT but no parametric exercises it. PUT
differs from PATCH in required-field semantics (DRF's default PUT
treats every writable field as required); a viewset can have separate
validation paths for the two methods.

**Why it matters.** A queryset that's correctly scoped on PATCH could
still be unscoped on PUT if `update()` is overridden. PUT body shapes
also differ — full replacement vs. partial — so DRF can hit different
serializer code paths.

**Approach.**

1. In `posthog/test/test_idor_coverage.py`, add a parametric:

   ```python
   @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
   def test_cross_team_put_detail(self, _name: str, case: IDORTestCase) -> None:
       """Attacker cannot replace a cross-team resource via PUT + no sentinel leak."""
       instance, url, sentinel = self._build_instance_and_url(case)
       try:
           body = build_minimal_post_body(case.viewset_cls.serializer_class, team=self.team)
       except (BodyUnfillable, Exception):
           # PUT requires a full body; fall back to a minimal PATCH-like body so
           # endpoints that allow partial PUTs still get exercised.
           body = {"name": "pwned", "title": "pwned", "description": "pwned"}
       response = self.assertCrossTeamDenied(url, method="put", data=body)
       self.assertSentinelNotLeaked(response, sentinel)
       _assert_resource_unchanged(self, case, instance, sentinel)
   ```

2. Reuse `_build_instance_and_url`, `_assert_resource_unchanged`,
   `build_minimal_post_body`. No new infrastructure needed.

**Effort.** S (~30 min including unit-test smoke check).

**File touchpoints.** `posthog/test/test_idor_coverage.py` only.

**Verification.** Run `flox activate -- bash -c "python -m pytest
posthog/test/idor/ -q"` (still 122+); run
`.github/scripts/check-idor-test-coverage.py` (no new uncovered).
Cherry-pick onto a known-vulnerable branch and verify the test fails
when the queryset is unscoped on PUT.

---

#### A4. Cross-tenant LIST endpoint isolation

**Missing.** Detail tests catch missing team filters on retrieve(); list
tests do not exist. A vulnerable viewset that enumerates all rows on
`GET /api/<root>/<id>/<resource>/` is invisible to the framework
today.

**Why it matters.** List endpoints are everywhere; missing `team_id`
filters here leak entire collections, not single records. Pagination +
search-filter combinations multiply the surface.

**Approach.**

1. New parametric `test_cross_team_list_isolation` in
   `posthog/test/test_idor_coverage.py`:

   ```python
   @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
   def test_cross_team_list_isolation(self, _name: str, case: IDORTestCase) -> None:
       """Listing on attacker's tenant must not include victim's resource."""
       sentinel = reset_sentinel()
       try:
           victim_instance = build_minimal_instance(case.model_cls, team=self.victim_team)
       except Exception as exc:
           self.skipTest(f"{case.model_cls.__name__}: could not build victim ({exc})")
       # Build the list URL on the attacker's tenant root.
       list_url = self._build_list_url_for_attacker(case)  # already exists
       if list_url is None:
           return
       response = self.client.get(list_url)
       if response.status_code >= 500:
           _maybe_warn_5xx(case.name, response.status_code)
           return
       if response.status_code not in range(200, 300):
           return  # 401/403/404 acceptable
       self.assertSentinelNotLeaked(response, sentinel)
       # Best-effort: parse JSON and assert victim pk is absent.
       try:
           payload = response.json()
       except Exception:
           return
       results = payload if isinstance(payload, list) else payload.get("results", [])
       victim_pk = str(victim_instance.pk)
       for row in results if isinstance(results, list) else []:
           if isinstance(row, dict) and str(row.get("id") or row.get("pk")) == victim_pk:
               raise AssertionError(
                   f"IDOR list leak: {list_url} returned victim {case.model_cls.__name__}(pk={victim_pk})"
               )
   ```

2. Reuse `_build_list_url_for_attacker` (already in
   `test_idor_coverage.py`). Reuse `reset_sentinel` /
   `assertSentinelNotLeaked` from the mixin.

**Effort.** S-M (~1 hour).

**File touchpoints.** `posthog/test/test_idor_coverage.py` only.

**Verification.** New parametric runs; existing tests unchanged.
Cherry-pick onto a branch where team filter is removed from a list
queryset; verify the test fails.

---

#### B4. Fix `AppMetricsViewSet` to return 404 for cross-team PluginConfig

**Missing.** `posthog/api/app_metrics.py:31` — `retrieve()` doesn't
validate that `kwargs["pk"]` belongs to `self.team`. Cross-team access
returns 200 with empty aggregation instead of 404.

**Why it matters.** Empty-200 leaks resource existence (attacker
confirms a PluginConfig at this id exists for someone). The skip-list
note documents this as the only `RETURNS_200_WITH_EMPTY_AGGREGATION`
entry.

**Approach.**

1. Edit `posthog/api/app_metrics.py:31` (start of `retrieve()`):

   ```python
   def retrieve(self, request, *args, **kwargs):
       try:
           # Validate ownership before running aggregations
           PluginConfig.objects.get(pk=kwargs["pk"], team=self.team)
       except PluginConfig.DoesNotExist:
           # Could be a batch-export id (string with "BatchExport" prefix);
           # let that path fall through to the existing logic.
           if "hog-" not in str(kwargs["pk"]):
               raise Http404
       # ... existing body
   ```

   Note: the retrieve method currently handles both PluginConfig pks
   and BatchExport ids — preserve that branching. Validate via the
   queryset only when the value looks numeric.

2. Remove `AppMetricsViewSet` from `IDOR_TEST_SKIP_LIST`.
3. Run `--update-snapshot` to refresh the coverage snapshot.

**Effort.** S (~15 min) — but **slight breaking change**: clients
relying on 200-empty get 404 instead. This is the correct behaviour
per the skip-list comment.

**File touchpoints.** `posthog/api/app_metrics.py`,
`posthog/test/idor/skip_list.py`,
`posthog/test/idor/_coverage_snapshot.json`.

**Verification.** Run the parametric for AppMetricsViewSet; should
pass without skip. Existing tests for AppMetrics may need updating.

---

#### A1.1 JSON-FK manual-review surface in CI report

**Missing.** 83 viewsets have writable `JSONField` / `DictField`. Many
contain tenant FK ids inside JSON (Cohort filters, FeatureFlag filters,
Insight queries, HogFlow trees, Alert configs). Discovery doesn't see
inside JSON, so 0 auto-coverage.

**Why it matters.** This is the single largest IDOR shape gap. JSON
properties are validated case-by-case in `save()` / `perform_create()`
— exactly where IDOR happens.

**Approach (step 1 only — manual surface).**

1. In `.github/scripts/check-idor-test-coverage.py`, add a section that
   enumerates writable JSON fields. Pseudocode:

   ```python
   from rest_framework import serializers as drf_ser

   json_fields_for_review: list[tuple[str, str]] = []
   for case in discover_idor_test_cases():
       sc = getattr(case.viewset_cls, "serializer_class", None)
       if not sc:
           continue
       try:
           instance = sc(context={"team_id": None, "request": None, "get_team": lambda: None})
           for name, field in instance.fields.items():
               if field.read_only:
                   continue
               if isinstance(field, (drf_ser.JSONField, drf_ser.DictField)):
                   json_fields_for_review.append((case.name, name))
       except Exception:
           pass

   print(f"\n[idor-json-review] writable JSON/Dict fields needing manual audit: {len(json_fields_for_review)}")
   for v, f in json_fields_for_review:
       print(f"  {v}.{f}")
   ```

2. Output is informational, not failure-causing.
3. Doc: in `.agents/security.md`, add a section explaining the manual
   audit checklist for JSON fields.

**Effort.** S (~1 hour).

**File touchpoints.** `.github/scripts/check-idor-test-coverage.py`,
`.agents/security.md`.

**Verification.** Run the script and confirm the report lists ~83
viewsets with their JSON field names.

---

### Tier 2 — high impact, medium effort

#### A2.1 Query-param IDORs on list endpoints

**Missing.** `GET /api/<root>/<id>/things/?cohort=victim_id` —
list-endpoint filters that aren't validated against tenant scope. 25
viewsets declare `filterset_fields` or `search_fields`; many of those
filter values point at tenant-scoped models.

**Why it matters.** Filter params are common, easy to overlook, and
look "safe" because they're query-string rather than path-segment.

**Approach.**

1. Add a new discovery helper in `posthog/test/idor/fk_discovery.py`:

   ```python
   def discover_filter_params(viewset_cls: type) -> list[FilterParam]:
       """Walk filterset_fields / search_fields; return entries whose
       names match a tenant-scoped model (via lookup_tenant_models_by_partial_name)."""
   ```

   `FilterParam` is a new dataclass: `(param_name, target_model,
scope)`.

2. Add a parametric `test_cross_tenant_filter_param` in
   `test_idor_coverage.py`:
   - Build victim resource of `target_model`.
   - Hit `GET <list_url>?<param_name>=<victim_pk>`.
   - Sentinel-leak check; assert response either rejects the filter or
     returns empty list.
3. Reuse existing `_build_list_url_for_attacker`,
   `build_minimal_instance`, `assertSentinelNotLeaked`.

**Effort.** M (3–4 hours).

**File touchpoints.** `posthog/test/idor/fk_discovery.py` (new helper +
new dataclass), `posthog/test/test_idor_coverage.py` (new parametric),
unit tests in `posthog/test/idor/test_fk_discovery.py`.

**Verification.** Cherry-pick onto a branch with `?cohort=` filter
that doesn't validate scope; verify the test fails.

---

#### A2.2 Query-param IDORs on `@action` endpoints

**Missing.** `@action(methods=["GET"])` endpoints with
`@extend_schema(parameters=[OpenApiParameter(name='dashboard_id',
...)])`. Currently filtered out (writable methods only).

**Why it matters.** Read actions (search, aggregate, summary) often
take an id parameter; same IDOR shape as filter params but on actions.

**Approach.**

1. Extend `discover_action_serializers` (or add
   `discover_action_parameters`) in `fk_discovery.py` to read
   `OpenApiParameter` entries from the same drf-spectacular closure
   path:

   ```python
   def _extract_extend_schema_parameters(schema_cls: type) -> list[OpenApiParameter]:
       # Mirror _extract_extend_schema_request but pull `parameters` freevar
   ```

2. Lift the writable-methods filter in `_iter_action_cases` to allow
   GET when the action has tenant-pointing parameters.
3. New parametric `test_cross_tenant_id_in_action_query_param` that
   hits `GET <action_url>?<param>=<victim_id>` instead of injecting
   into a body.

**Effort.** M (3–4 hours).

**File touchpoints.** `posthog/test/idor/fk_discovery.py`,
`posthog/test/test_idor_coverage.py`,
`posthog/test/idor/test_fk_discovery.py`.

**Verification.** New parametric exercises ~5–10 GET actions; cherry-
pick onto a branch with a vulnerable action and verify failure.

---

#### A1.2 Runtime probes for top JSON-FK shapes

**Missing.** 0 runtime coverage of FK ids embedded in JSON properties.

**Why it matters.** Highest-value targets known: Cohort.groups,
FeatureFlag.filters, Insight.query, HogFlow tree, Alert.config.

**Approach.**

1. New module `posthog/test/idor/json_fk_probes.py`. Each probe is a
   per-shape function that:
   - Takes a body dict and a victim id.
   - Walks the JSON tree following the shape's known structure (e.g.,
     `groups[].properties[].value` for Cohort filters).
   - Replaces the deepest `<thing>_id` value with the victim's pk.
   - Returns the mutated body.
2. Per-shape registration:

   ```python
   register_json_probe(serializer_class=CohortSerializer, field="filters",
                       inject_fn=_cohort_filter_inject, target_model=Cohort)
   ```

3. New parametric `test_cross_tenant_fk_in_json` iterates the registry,
   builds the body via `build_minimal_post_body`, runs each probe, and
   POSTs/PATCHes against the attacker's URL with the victim's id
   smuggled. Reuse the existing 5xx-warning + leak-check pattern.
4. Start with 5 shapes (one per high-value model). Add more as
   serializers expose new JSON contents.

**Effort.** L (1–2 days for first 5 shapes; ongoing thereafter).

**File touchpoints.** `posthog/test/idor/json_fk_probes.py` (new),
`posthog/test/test_idor_coverage.py` (new parametric),
`posthog/test/idor/test_json_fk_probes.py` (new unit tests),
`.semgrep/rules/idor-team-scoped-models.yaml` (potentially adding
referenced models if missing).

**Verification.** For each registered probe, write a canary test that
demonstrates the probe finds and rejects the cross-tenant id.

---

#### C5. Pagination cursor / offset leaks

**Missing.** List parametrics (once added per A4) check the first page
only. `?cursor=`, `?offset=`, `?after=` could include cross-tenant
rows in subsequent pages.

**Why it matters.** Niche but real — paginators that query unscoped
querysets only enforce tenant scope on the first slice.

**Approach.**

1. Extend the A4 list parametric to also follow `next` links in
   paginated responses (DRF's `LimitOffsetPagination` /
   `PageNumberPagination` / cursor pagination all expose `next`).
2. Cap at depth 3 pages to avoid runaway test time.
3. Sentinel-leak + pk-presence check on every page.

**Effort.** M (half day) once A4 is in place.

**File touchpoints.** `posthog/test/test_idor_coverage.py`.

**Verification.** Paginate a list endpoint with at least 2 pages of
victim data; confirm the test catches a leak in page 2.

---

### Tier 3 — medium impact, medium effort

#### A5. Body fixtures for `BodyUnfillable` skips

**Ongoing work.** Each skip in the FK-POST and action parametrics is a
missed run. Pattern:

1. Run the parametric, capture skip messages with reason
   `BodyUnfillable`.
2. For each skip, locate the serializer's `validate()` / shape
   constraint.
3. Register a body factory in
   `posthog/test/idor/post_body_fixtures.py`:

   ```python
   def _foo_body(team: Team) -> dict[str, Any]:
       return {...}  # body that satisfies the validator
   register_post_body(FooSerializer, _foo_body)
   ```

4. Re-run; the test moves from SKIPPED → PASSED.

**Effort.** ~1 hour per fixture, ~30 min per skip cause. Iterative.

**File touchpoints.** `posthog/test/idor/post_body_fixtures.py` only.

---

#### A6.1 Personal API key (PAK) attack context

**Missing.** Attacker is always session-authenticated. PAKs have
distinct scope semantics — a PAK with team_id scope shouldn't access
other teams; a PAK with org-wide scope might.

**Why it matters.** PAK auth is independent of session auth; some
endpoints branch on auth type. A queryset that's correctly scoped for
session auth could still be unscoped for PAK auth if `get_queryset`
ignores `request.auth`.

**Approach.**

1. Extend `IDORTestMixin` to provide an alternative
   `attacker_pak_client` — a `Client` instance with PAK auth headers
   set.
2. New parametric variant `test_cross_team_get_detail_via_pak` that
   reuses the same URL set + assertions but uses the PAK client.
3. Per-PAK-scope variants: scope=team_only, scope=org_wide,
   scope=read_only.
4. Track PAK skips in a dedicated category in
   `IDOR_TEST_SKIP_LIST` (`PAK_NOT_APPLICABLE`).

**Effort.** L (1–2 days).

**File touchpoints.** `posthog/test/idor/mixin.py` (add PAK client),
`posthog/test/test_idor_coverage.py` (new parametric variants),
`posthog/test/idor/skip_list.py` (new category).

**Verification.** Cherry-pick onto a branch that ignores PAK scope on
queryset; verify the test fails.

---

#### A6.2 Sharing token attack context

**Missing.** Sharing tokens allow read-only access to specific
resources (dashboards, insights). A bug here lets the token holder
read other resources in the same tenant via parameter substitution.

**Why it matters.** Sharing tokens are a documented attack surface;
public-share IDORs are a common bug class.

**Approach.**

1. Identify sharing-token-aware viewsets (look for
   `SharingTokenPermission` in `permission_classes`).
2. New mixin method `_sharing_token_for(model_cls, team)` returns a
   minted token for a specific resource.
3. New parametric `test_sharing_token_does_not_grant_other_resources`:
   issue a token for resource A, attempt to access resource B in the
   same tenant via `?sharing_access_token=<token>` and a different pk.

**Effort.** L (1–2 days).

**File touchpoints.** `posthog/test/idor/mixin.py`,
`posthog/test/test_idor_coverage.py`.

**Verification.** Mint a sharing token; verify access to other
resources is denied.

---

#### B2. NO_MODEL viewset coverage (selective)

**Missing.** 10 viewsets in `IDOR_TEST_SKIP_LIST` with
`category=NO_MODEL`. Team scoping pushed into facade / query layer.

**Per-viewset assessment** (from prior audit):

| Viewset                               | Approach                                        |
| ------------------------------------- | ----------------------------------------------- |
| ErrorTrackingExternalReferenceViewSet | Hand-written cross-team test (~S)               |
| ErrorTrackingFingerprintViewSet       | Document parent-issue dependency; skip stays    |
| EventViewSet                          | Skip; ClickHouse-side; semgrep + manual review  |
| FixHogQLViewSet                       | N/A — POST action, no detail                    |
| HistoricalExportsAppMetricsViewSet    | Skip; aggregation endpoint                      |
| LegalDocumentViewSet                  | Cross-org test (~S, depends on A6.2 if sharing) |
| QueryViewSet                          | Hand-written; query_id scoping (~M)             |
| RepoViewSet                           | Hand-written cross-team test (~S)               |
| RunViewSet                            | Hand-written cross-team test (~S)               |
| SessionGroupSummaryViewSet            | N/A — POST action                               |

**Approach.** For testable ones, write product-local hand-written
tests in `products/<product>/backend/tests/`. Document the approach in
`.agents/security.md` so new NO_MODEL viewsets get tests too.

**Effort.** S–M per viewset; ~6–8 hours total for 4–5 testable cases.

---

#### E4. User-in-org FK detection

**Missing.** Fields like `created_by_id`, `owner_id`,
`mentioned_user_id` resolve to `User`, which is global. The expected
behaviour is that the user must be in the same org as the creating
team. Discovery currently skips User as non-tenant-scoped.

**Why it matters.** Real bug class — a model can let an attacker
transfer ownership across orgs by setting `owner_id` to a foreign
user.

**Approach.**

1. Extend `fk_target_models.py` allowlist concept: track "user-in-org"
   target shape.
2. In `_classify_explicit_fk`, when target is `User` AND the model has
   a `<thing>__organization` constraint (or none, in which case it's
   vulnerable), emit a record with `scope=user_in_org`.
3. Reuse the existing `victim_user_in_foreign_org` fixture (already in
   `mixin.py` per Phase 5a).

**Effort.** M (1 day).

**File touchpoints.** `posthog/test/idor/fk_target_models.py`,
`posthog/test/idor/fk_discovery.py`,
`posthog/test/idor/mixin.py`.

---

#### D1. Complex bulk shapes

**Missing.** Bulk endpoints with shapes other than `<thing>_ids =
ListField`:

- `{operations: [{type: "delete", id: X}, ...]}`
- `{ids: [...], action: "delete"}`
- Per-item validation arrays

**Approach.** Extend `body_factory.py` with a recognizer for these
patterns. Probably needs per-pattern registration since each shape is
slightly different.

**Effort.** M (1 day for 2–3 common shapes).

**File touchpoints.** `posthog/test/idor/body_factory.py`,
`posthog/test/idor/fk_discovery.py`.

---

### Tier 4 — low priority / specialised

#### C1. Richer leak detection

**Missing.** Sentinel matching is substring-only on decoded body text.
Doesn't catch:

- Numeric pk leaks (victim's int pk in response)
- Header leaks (`X-Resource-Id: <victim>`)
- Binary streams / file content leaks
- Structural fingerprints (response shape confirms existence even if
  content is empty)

**Approach.**

1. Extend `assertSentinelNotLeaked` to optionally accept additional
   tokens (numeric pks, names) via `additional_sentinels`.
2. Add `assertResponseShapeNotLeak` that checks for known
   resource-revealing shape patterns (e.g., 200 with `{id: ...}` even
   if values are zero).
3. Header inspection: walk response headers for any of the known
   sentinels.

**Effort.** L (1–2 days).

**File touchpoints.** `posthog/test/idor/mixin.py`, every parametric.

---

#### C3. Promote 5xx warnings to errors

**Missing.** `_maybe_warn_5xx` emits `warnings.warn`; CI doesn't
escalate.

**Approach.** Once `IDOR_5XX_KNOWN_LATENT` is populated with the
genuinely understood cases, change the warn to a test failure for
unlisted entries.

**Effort.** S (~1 hour).

**File touchpoints.** `posthog/test/test_idor_coverage.py::_maybe_warn_5xx`.

---

#### D3. Header-based identifier IDORs

**Missing.** Endpoints that read `X-Project-Id` (or similar) from
headers instead of URL.

**Effort.** M.

---

#### D4. Multipart / file upload IDORs

**Missing.** Endpoints accepting file uploads (UploadedMedia,
BatchImport).

**Effort.** L (fixture-heavy).

---

#### A6.3 OAuth token contexts

**Missing.** OAuth2-issued tokens.

**Effort.** L; depends on OAuth product surface.

---

#### B1. LEGACY_FLAT_URL viewsets

**Recommendation: skip.** All 8 entries are slated for removal. Test
machinery for soon-to-delete routes is wasted effort.

---

### Tier 5 — adjacent (not strictly IDOR but related)

| #      | Gap                                         | Notes                                                                                            |
| ------ | ------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **E1** | Activity log readability across tenants     | Activity logs are FK to team; check that `GET /api/.../activity_logs/?team_id=victim` is denied. |
| **E2** | Cache-key collisions (Insight, query cache) | Hit endpoint as victim, then as attacker; assert cache doesn't return victim data.               |
| **E3** | Webhook callback URL IDORs                  | Webhooks accept callbacks with team-id query params; verify validation.                          |

---

## Recommended execution order

### Phase 1 — Tier 1 quick wins (~3–4 hours total)

| Order | Item                                   | Effort | Removes / adds                    |
| ----- | -------------------------------------- | ------ | --------------------------------- |
| 1     | **B4** AppMetricsViewSet 1-line fix    | S      | 1 viewset off skip list, real bug |
| 2     | **A3** PUT detail parametric           | S      | +131 cases × 1 method             |
| 3     | **A4** Cross-tenant LIST isolation     | S-M    | +131 viewsets in a new shape      |
| 4     | **A1.1** JSON-FK manual-review surface | S      | Punch list for 83 viewsets        |

After Phase 1: 7 → 9 parametrics, full standard HTTP method surface
exercised.

### Phase 2 — Tier 2 medium-effort (~1–2 weeks)

| Order | Item                                          | Effort |
| ----- | --------------------------------------------- | ------ |
| 5     | **A2.1** Query-param IDOR on list endpoints   | M      |
| 6     | **A2.2** Query-param IDOR on @action GETs     | M      |
| 7     | **A1.2** Runtime probes for top 5 JSON shapes | L      |
| 8     | **C5** Pagination leak detection              | M      |

### Phase 3 — Tier 3 (~1–2 weeks)

| Order | Item                                           | Effort  |
| ----- | ---------------------------------------------- | ------- |
| 9     | **A5** Body fixtures (ongoing)                 | M-L per |
| 10    | **A6.1** PAK attacker context                  | L       |
| 11    | **A6.2** Sharing-token attacker context        | L       |
| 12    | **B2** NO_MODEL hand-written tests (4–5 of 10) | M total |
| 13    | **E4** User-in-org FK detection                | M       |
| 14    | **D1** Complex bulk shapes                     | M       |

### Phase 4 — Tier 4 (specialised)

15. **C1** Richer leak detection
16. **C3** 5xx warning → error promotion
17. **D3** Header-based IDOR
18. **D4** Multipart upload IDOR
19. **A6.3** OAuth token attacker

### Don't pursue

- **B1** LEGACY_FLAT_URL — slated for removal

---

## How to verify progress

After each item:

```bash
# Unit tests stay green
flox activate -- bash -c "python -m pytest posthog/test/idor/ -q --no-header"

# CI gate stays green; refresh snapshot if pairs changed
flox activate -- bash -c "python .github/scripts/check-idor-test-coverage.py"
flox activate -- bash -c "python .github/scripts/check-idor-test-coverage.py --update-snapshot"

# Full integration sweep (slow; needs DB)
hogli test posthog/test/test_idor_coverage.py
```

For each item, write **canary tests** in
`posthog/test/idor/test_fk_canary.py` (or a new equivalent) that
demonstrate the framework would catch the IDOR if it were reintroduced.

---

## Investigation prompts (for an agent picking this up)

```python
# Current discovery state
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()
from posthog.test.idor.discovery import discover_idor_test_cases
from posthog.test.idor.fk_discovery import discover_writable_tenant_fks, discover_action_serializers
cases = discover_idor_test_cases()
print(f"viewsets: {len(cases)}")
total_fks = sum(
    len(discover_writable_tenant_fks(c.viewset_cls.serializer_class))
    for c in cases
    if hasattr(c.viewset_cls, "serializer_class") and c.viewset_cls.serializer_class
)
print(f"FKs:      {total_fks}")
total_actions = sum(len(discover_action_serializers(c.viewset_cls)) for c in cases)
print(f"actions:  {total_actions}")
```

Find writable JSON fields (Tier 1, A1.1):

```python
from rest_framework import serializers as drf_ser
for c in cases:
    sc = getattr(c.viewset_cls, "serializer_class", None)
    if not sc: continue
    try:
        ins = sc(context={"team_id": None, "request": None, "get_team": lambda: None})
        for name, f in ins.fields.items():
            if not f.read_only and isinstance(f, (drf_ser.JSONField, drf_ser.DictField)):
                print(c.name, name)
    except Exception:
        pass
```

Find filter-param viewsets (Tier 2, A2.1):

```python
for c in cases:
    if getattr(c.viewset_cls, "filterset_fields", None) or getattr(c.viewset_cls, "search_fields", None):
        print(c.name, getattr(c.viewset_cls, "filterset_fields", None), getattr(c.viewset_cls, "search_fields", None))
```

Find actions without `@extend_schema(request=...)` (Tier 3, A5
candidates):

```python
for c in cases:
    if not hasattr(c.viewset_cls, "get_extra_actions"): continue
    for a in c.viewset_cls.get_extra_actions():
        if (a.kwargs or {}).get("schema") is None:
            print(c.name, a.__name__)
```

---

## Skip-list philosophy (recap)

Skip-loud, never silent. Every skip needs a documented category +
reason. Categories:

- **`{X}_NOT_TESTABLE`** — auto-machinery can't reach this (custom
  lookup field, no model, etc.)
- **`INTENTIONAL_CROSS_TENANT_*`** — the FK / endpoint is meant to
  span tenants (rare; document the threat model).
- **`BODY_SYNTHESIS_INFEASIBLE`** — needs a registered body fixture.
- **`POST_NOT_ALLOWED`** — viewset's `create` is disabled or 405s.
- **`REQUIRES_FILESYSTEM_OR_TEMPORAL`** — POST triggers heavy side
  effects.
- **`LATENT_*_BUG`** — known server bug; tracked here with link to
  fix.
- **`LEGACY_FLAT_URL`** — pinned to `request.user.current_team`,
  slated for removal.
- **`NO_MODEL`** — wraps ClickHouse / external services with no
  Django model.
- **`TENANT_ROOT_RESOURCE`** — covered by `tenant_root.py` parametric;
  this category is now empty.
- **`CUSTOM_LOOKUP_FIELD`** — string-based key lookups (rare after
  short_id support shipped).
- **`RETURNS_200_WITH_EMPTY_AGGREGATION`** — viewset returns 200 with
  empty data instead of 404 (B4).
