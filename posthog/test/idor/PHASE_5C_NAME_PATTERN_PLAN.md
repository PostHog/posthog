# Phase 5c: Name-pattern cross-tenant references on @action endpoints

## Context

Phases 5a + 5b cover writable tenant-FK fields on the standard
`serializer_class` (PATCH detail URL, POST list URL). They miss IDORs
shaped like `tom/dashboard-template`:

```python
class CopyDashboardTemplateSerializer(serializers.Serializer):  # not a ModelSerializer
    source_template_id = serializers.UUIDField(...)

class DashboardTemplateViewSet(...):
    @extend_schema(request=CopyDashboardTemplateSerializer, ...)
    @action(detail=False, methods=["post"], url_path="copy_between_projects")
    def copy_between_projects(self, request, **kwargs):
        source = DashboardTemplate.objects_including_soft_deleted.filter(
            id=body.validated_data["source_template_id"]
        ).first()  # NO TEAM SCOPING
```

Two miss dimensions:

1. **Detection** — `fk_discovery.py::_classify_implicit_id` resolves
   `<thing>` against `Meta.model._meta.get_field()`. A plain
   `serializers.Serializer` has no `Meta.model`, so the field is
   skipped.
2. **Runtime** — `test_cross_tenant_fk_in_post` POSTs to the standard
   list URL with the viewset's main serializer. Custom `@action` URLs
   with action-specific serializers are not exercised.

## Decisions

1. **Generalize implicit detection.** Add a "name pattern" path that
   maps `<thing>_id` to tenant-scoped models by name lookup against the
   semgrep allowlist (case-insensitive snake*case to PascalCase, with
   `source*`/`target*`/`from*`/`to\_`prefix stripping). Works on
any`serializers.Serializer`, ModelSerializer or not.
2. **Discover @action request serializers** via drf-spectacular's
   `_spectacular_annotation` attribute that `@extend_schema(request=…)`
   sets on the bound method. Fall back to walking the action's
   url_path attribute when the schema annotation is missing.
3. **Custom action URL builder** — extend `URLStructure` with
   `build_action_url(action_url_path)` that appends the action segment
   to the list URL.
4. **One new parametric** — `test_cross_tenant_id_in_action` covers
   `(viewset × action × writable name-pattern field)`. POST/PATCH the
   action URL with the victim's pk in the field, expect non-2xx.
5. **Skip-loud** — actions whose URL we can't build, whose body we
   can't synthesize, or whose method we don't support all `skipTest()`
   rather than asserting a false signal. New `IDOR_ACTION_SKIP_LIST`
   tracks viewsets where the action shape is intentionally unusual.

## Architecture

```text
posthog/test/idor/
  fk_discovery.py            # MODIFY: name-pattern path + action discovery
  url_structure.py           # MODIFY: build_action_url()
  skip_list.py               # MODIFY: add IDOR_ACTION_SKIP_LIST
  test_fk_discovery.py       # MODIFY: add tests for name-pattern + action discovery
  test_fk_canary.py          # MODIFY: name-pattern canary
posthog/test/
  test_idor_coverage.py      # MODIFY: add test_cross_tenant_id_in_action parametric
.agents/
  security.md                # MODIFY: document the new shape
```

## Name pattern mapping

Snake-cased `<thing>` segment maps to a tenant-scoped model class name.
Examples (against the semgrep allowlist):

| Field name           | Stripped                           | PascalCase          | Match in allowlist                          |
| -------------------- | ---------------------------------- | ------------------- | ------------------------------------------- |
| `template_id`        | `template`                         | `Template`          | look for fuzzy match: `DashboardTemplate` ✓ |
| `source_template_id` | `template` (after `source_` strip) | `DashboardTemplate` | ✓                                           |
| `dataset_id`         | `dataset`                          | `Dataset`           | ✓                                           |
| `feature_flag_id`    | `feature_flag`                     | `FeatureFlag`       | ✓                                           |
| `cohort_id`          | `cohort`                           | `Cohort`            | ✓                                           |
| `team_id`            | `team`                             | `Team`              | (tenant root, special-case)                 |
| `created_by_id`      | `created_by`                       | `CreatedBy`         | (no match — User is not tenant-scoped)      |

To keep false positives low, we require BOTH:

- The stripped `<thing>` matches a tenant-scoped model name with a
  case-insensitive partial match (e.g., `template` → `DashboardTemplate`)
- The serializer is on a viewset that's mounted under
  `/projects|environments|organizations/{id}/...`

Common stripping prefixes: `source_`, `target_`, `from_`, `to_`,
`new_`, `old_`, `parent_`, `child_`. Suffixes: `_id`, `_ids`.

## Action discovery

drf-spectacular sets `method._spectacular_annotation` (a dict) on
methods decorated with `@extend_schema`. The dict contains the
`request` serializer reference. Pull it via:

```python
extra = viewset_cls.get_extra_actions()
for action_method in extra:
    annotation = getattr(action_method, "_spectacular_annotation", {})
    request_serializer = annotation.get("request")
    if request_serializer is None:
        # Fallback: methods without @extend_schema use the viewset's serializer_class.
        # No new IDOR shape there; the standard parametric covers it.
        continue
    yield (action_method.__name__, action_method.kwargs.get("url_path", action_method.__name__),
           action_method.kwargs.get("methods", ["GET"]), request_serializer)
```

## Test logic

```python
def test_cross_tenant_id_in_action(self, _name, case, action_meta, fk):
    if action_meta.method not in {"POST", "PATCH", "PUT"}:
        self.skipTest(...)  # GET-shaped actions don't have writable bodies
    try:
        body = build_minimal_post_body(action_meta.serializer_cls, team=self.team)
    except BodyUnfillable as e:
        self.skipTest(...)
    victim_fk = build_minimal_instance(fk.target_model, team=self.victim_team)
    body[fk.serializer_field_name] = str(victim_fk.pk)
    url = case.url.build_action_url(root_id=self.team.pk, action_url_path=action_meta.url_path)
    response = self.client.generic(action_meta.method, url, data=body, format="json")
    if response.status_code >= 500:
        self.skipTest(...)
    if response.status_code not in range(200, 300):
        return  # rejected — pass
    # 2xx: the action proceeded. Whether this is an IDOR depends on the
    # action's semantics. We rely on the response body NOT containing
    # the victim resource's known string fields (sentinel-leak detection).
    self.assertSentinelNotLeaked(response, ...)
```

The mutation-side check is fuzzier than for PATCH/POST because each
action has different semantics. The test treats 2xx as "needs review"
and falls back to sentinel-leak detection on the response body.

## Implementation steps (5 commits)

### 1. Generalized name-pattern detection

- `fk_discovery.py`: add `_classify_name_pattern_id()` that works on
  any Serializer (no Meta.model required). Map `<thing>_id` to tenant-
  scoped target via case-insensitive partial match.
- `WritableFKField.is_name_pattern: bool = False` flag.
- Unit tests in `test_fk_discovery.py`.
- **Commit**: `feat(idor-tests): detect name-pattern <thing>_id on any Serializer`

### 2. Action serializer discovery

- `fk_discovery.py`: `discover_action_serializers(viewset_cls)` walks
  `get_extra_actions()` and pulls request serializer from
  `_spectacular_annotation`.
- Returns list of `ActionSerializerCase(action_method, url_path, methods, serializer_cls)`.
- Unit tests with a fake viewset declaring an `@extend_schema(request=...)` action.
- **Commit**: `feat(idor-tests): discover @action request serializers via drf-spectacular`

### 3. URL builder + skip list

- `url_structure.py`: `build_action_url(root_id, action_url_path, intermediate_ids=None)`.
- `skip_list.py`: `IDOR_ACTION_SKIP_LIST` with categories
  `ACTION_NOT_TESTABLE`, `INTENTIONAL_CROSS_TENANT`, `BODY_SYNTHESIS_INFEASIBLE`.
- Unit tests + test_coverage_check well-formedness.
- **Commit**: `feat(idor-tests): URLStructure.build_action_url + IDOR_ACTION_SKIP_LIST`

### 4. Action parametric test

- `test_idor_coverage.py`: `test_cross_tenant_id_in_action`.
- Uses existing `_assert_single_fk_not_bound_to_victim` style with
  fallback to sentinel-leak detection.
- **Commit**: `feat(idor-tests): add cross-tenant id-in-action variant`

### 5. Documentation + canary

- `test_fk_canary.py`: name-pattern canary.
- `.agents/security.md`: document the new shape.
- **Commit**: `docs(security): document Phase 5c name-pattern coverage`

## Verification

1. The framework should detect `CopyDashboardTemplateSerializer.source_template_id`
   on the deleted `copy_between_projects` action.
2. The runtime test, when run on the pre-fix branch (commit 69cf256ee5a),
   should fail loudly because the action returns 2xx with the victim's
   template content.

## Out of scope

- Action methods that take complex multi-FK bodies (e.g., bulk_update
  endpoints) — narrower per-action fixture work, not framework-level.
- Actions that depend on Temporal workflows or external services —
  add to `IDOR_ACTION_SKIP_LIST` under `REQUIRES_FILESYSTEM_OR_TEMPORAL`.
- Field names that don't follow `<thing>_id` convention (e.g.,
  `template`, `dashboard`) — these are already covered by the explicit
  PrimaryKeyRelatedField path when properly typed; the dashboard-template
  case explicitly used `_id` suffixed UUID, so the pattern catches it.

## Expected deltas

| Metric                    | Before                                           | After                                              |
| ------------------------- | ------------------------------------------------ | -------------------------------------------------- |
| Discovery shapes          | explicit / implicit (ModelSerializer only) / M2M | + name-pattern (any Serializer)                    |
| Action serializers walked | 0                                                | every `@action` with `@extend_schema(request=...)` |
| Parametric tests          | 62 (PATCH+POST)                                  | + ~10–25 action tests                              |
| IDOR shapes covered       | detail scoping + FK PATCH + FK POST              | + name-pattern in action                           |

## Unresolved

None — design is concrete. Implementation will surface tuning needs
(action-specific body fixtures, skip-list entries) handled in follow-up.
