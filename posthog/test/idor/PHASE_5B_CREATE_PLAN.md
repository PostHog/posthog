# Phase 5b: Cross-tenant FK in CREATE (POST)

## Context

Phase 5a covered detail-URL queryset scoping plus FK-in-PATCH. PATCH alone misses every IDOR shape where the FK is **immutable after create** — the queryset only matters at POST time, and the field becomes read-only later. Examples: `Node.dag`, `PluginConfig.plugin`, `ExportedAsset.dashboard`.

This phase adds `test_cross_tenant_fk_in_post`: attacker POSTs a _new_ resource into their own team's list URL, smuggling a victim's tenant FK pk into a writable field. A vulnerable serializer accepts it, binding the new resource to the victim's record across tenant boundaries.

## Decisions

1. **Reuse FK discovery.** The same `discover_writable_tenant_fks` runs over the same serializers. The PATCH and POST tests differ only in body construction and verification.
2. **Hybrid body synthesis.** Generic introspection (DRF `field` walk + sensible defaults) covers the easy cases; a registry of per-viewset POST body factories covers the hard ones (custom validators, mutually-exclusive fields, choice enums).
3. **Skip-loud.** If body synthesis can't satisfy the serializer, skip with a hint instead of asserting.
4. **CI gate.** Add a dedicated `idor-tests` job triggered on every backend change so product-isolated PRs still run the parametric.

## Architecture

```text
posthog/test/idor/
  body_factory.py            # NEW: build_minimal_post_body(serializer_cls, team)
  post_body_fixtures.py      # NEW: per-viewset POST body factory registry
  test_body_factory.py       # NEW: unit tests
posthog/test/
  test_idor_coverage.py      # MODIFY: add test_cross_tenant_fk_in_post
posthog/test/idor/
  skip_list.py               # MODIFY: add IDOR_FK_POST_SKIP_LIST
  test_fk_canary.py          # MODIFY: canary for FK-in-POST
.github/workflows/
  ci-backend.yml             # MODIFY: add idor-tests job
.agents/
  security.md                # MODIFY: document POST coverage
```

## Body synthesis strategy

Generic synthesizer fills required, writable fields with sensible defaults:

| Field type                               | Default                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------ |
| `CharField` / `TextField` / `EmailField` | sentinel string (truncated to `max_length`)                              |
| `IntegerField` / `FloatField`            | `0`                                                                      |
| `BooleanField`                           | `False`                                                                  |
| `DateField` / `DateTimeField`            | `now()`                                                                  |
| `JSONField` / `DictField` / `ListField`  | `{}` / `[]`                                                              |
| `ChoiceField`                            | first choice                                                             |
| `UUIDField`                              | random uuid4                                                             |
| `PrimaryKeyRelatedField`                 | builds a tenant-scoped instance via `build_minimal_instance`, returns pk |
| `ManyRelatedField`                       | `[]`                                                                     |
| nested `ModelSerializer`                 | recurse                                                                  |

If a required field can't be filled (custom field type, unknown choices, etc.), the synthesizer raises `BodyUnfillable`. The test catches and skips.

The registry overrides take precedence — register per-viewset factories for serializers with custom `validate()` (e.g., `MessageTemplate` requires `content.email.subject` if `type='email'`).

## Test logic

```python
@parameterized.expand(FK_POST_CASES)
def test_cross_tenant_fk_in_post(self, _name, case, fk):
    # 1. Synthesize a body that should pass validation in the attacker's team.
    try:
        body = build_minimal_post_body(case.viewset_cls.serializer_class, team=self.team)
    except BodyUnfillable as e:
        self.skipTest(f"{case.name}.{fk.serializer_field_name}: {e}")

    # 2. Create the victim FK target.
    try:
        victim_fk = build_minimal_instance(fk.target_model, team=self.victim_team)
    except Exception as e:
        self.skipTest(...)

    # 3. Inject victim FK into body (top-level or nested).
    body = _inject_fk(body, fk, victim_fk.pk)

    # 4. POST to list URL.
    list_url = case.url.build_list_url(root_id=self.team.pk)
    response = self.client.post(list_url, data=body, format="json")

    # 5. Pass cases:
    #    - Non-2xx: validation rejected. Pass.
    #    - 2xx + created instance's FK != victim_pk: silently dropped. Pass.
    #    - 5xx: treat as skip (latent bug, not a leak signal).
    if response.status_code >= 500:
        self.skipTest(...)
    if response.status_code not in range(200, 300):
        return
    # 6. Verify the created resource didn't bind the victim FK.
    instance = case.model_cls.objects.get(pk=response.data["id"])
    if fk.is_many:
        _assert_m2m_does_not_contain_victim(instance, fk, victim_fk.pk, list_url, case)
    else:
        _assert_single_fk_not_bound_to_victim(instance, fk, victim_fk.pk, list_url, case)
```

## URL helpers

`url_structure.py` has `build_url(root_id, pk, intermediate_ids)`. Need `build_list_url(root_id, intermediate_ids)` (no pk; one trailing slash). Light extension.

## Skip list dimensions

Anticipated `IDOR_FK_POST_SKIP_LIST` categories:

- `POST_NOT_ALLOWED` — viewset doesn't expose `create` (e.g., read-only or detail-only viewsets).
- `BODY_SYNTHESIS_INFEASIBLE` — serializer requires custom shape we can't auto-build, no fixture registered.
- `INTENTIONAL_CROSS_TENANT_FK` — FK is meant to span tenants.
- `REQUIRES_FILESYSTEM_OR_TEMPORAL` — POST kicks off side effects (workflow, file write) we don't want in the test path.

Estimated initial size: 5–15 entries.

## CI integration

Today: `posthog/test/test_idor_coverage.py` runs as part of the Django legacy matrix, gated on `legacy == 'true'` OR `turbo-discover.run_legacy == 'true'`. Isolated product PRs skip it.

Fix: add a small dedicated `idor-tests` job in `.github/workflows/ci-backend.yml`:

- Triggers on `needs.changes.outputs.backend == 'true'` (every backend change).
- Postgres only (no ClickHouse needed; the IDOR tests don't query CH).
- Runs `pytest posthog/test/test_idor_coverage.py posthog/test/idor/ --tb=short --timeout=120`.
- ~5 min timeout.
- Lightweight setup so it stays fast.

This gives product-isolated PRs the same IDOR coverage as legacy PRs.

## Implementation steps (8 commits)

### 1. Body factory (generic synthesis)

- `posthog/test/idor/body_factory.py` with `build_minimal_post_body()` + `BodyUnfillable`
- `posthog/test/idor/test_body_factory.py` with fake serializers covering each field type
- **Commit**: `feat(idor-tests): synthesize minimal POST body via DRF introspection`

### 2. Body fixture registry

- `posthog/test/idor/post_body_fixtures.py` parallel to `fixtures.py`
- Register a few hard cases (MessageTemplate at minimum; add more as needed when the parametric runs)
- **Commit**: `feat(idor-tests): per-viewset POST body fixture registry`

### 3. URL list-builder

- Extend `url_structure.py::URLStructure.build_list_url()`
- Unit test
- **Commit**: `feat(idor-tests): URLStructure.build_list_url for POST tests`

### 4. POST parametric

- Extend `test_idor_coverage.py`:
  - `_iter_fk_post_cases()` — same iteration as PATCH but filtered to viewsets that allow POST
  - `test_cross_tenant_fk_in_post`
  - `_inject_fk(body, fk, victim_pk)` helper for top-level + nested + many=True
- Reuse `_assert_single_fk_not_bound_to_victim` / `_assert_m2m_does_not_contain_victim`
- **Commit**: `feat(idor-tests): add cross-tenant FK-in-POST variant`

### 5. Skip list

- Add `IDOR_FK_POST_SKIP_LIST` to `skip_list.py` with documented categories
- Extend `test_coverage_check.py` for well-formedness
- Extend `check-idor-test-coverage.py` to count POST coverage
- **Commit**: `chore(idor-tests): add IDOR_FK_POST_SKIP_LIST + categories`

### 6. Canary

- Extend `test_fk_canary.py` with a vulnerable POST serializer + simulated 200 response → assertion fires
- **Commit**: `test(idor-tests): canary for FK-in-POST detection`

### 7. CI job

- Add `idor-tests` job in `.github/workflows/ci-backend.yml`
- Triggered on `needs.changes.outputs.backend == 'true'`
- Postgres + Django; runs `pytest posthog/test/test_idor_coverage.py posthog/test/idor/`
- **Commit**: `chore(ci): dedicated IDOR test job runs on backend changes`

### 8. Documentation

- `.agents/security.md`: document the POST variant + how to register a body fixture
- **Commit**: `docs(security): document Phase 5b POST coverage expectations`

## Verification

1. `python -m pytest posthog/test/idor/test_body_factory.py posthog/test/idor/test_fk_canary.py` — unit + canary
2. `python -m pytest posthog/test/test_idor_coverage.py -k test_cross_tenant_fk_in_post --tb=short` — full sweep, expect ~25–35 cases (subset of FK pairs that survive POST gating)
3. `python .github/scripts/check-idor-test-coverage.py` — surface POST counts
4. Confirm the new CI job triggers on a product-only file change

## Expected deltas

| Metric                  | Before                    | After                                   |
| ----------------------- | ------------------------- | --------------------------------------- |
| Parametric tests        | ~352                      | ~377–387                                |
| FK PATCH cases          | 32                        | 32 (unchanged)                          |
| FK POST cases           | 0                         | 25–35                                   |
| CI gates                | 3                         | 4 (+ dedicated idor-tests job)          |
| Classes of IDOR covered | detail scoping + FK PATCH | + FK POST (CREATE-only writable fields) |

## Out of scope

- **Body synthesis robustness across all 108 viewsets** — start with introspection + a handful of fixtures. Expect some test cases to skip; that's fine until someone needs the coverage.
- **Cross-org POST gating** — the test always POSTs into the attacker's own team. Cross-org viewsets (e.g., OrganizationMembership creation) are tested via the existing org-scoped FK shapes; specific cross-org POST testing is Phase 5d-class work.
- **Dependent FKs** — when a serializer requires multiple tenant FKs (e.g. an Insight with both `dashboard` and `feature_flag`), the synthesizer fills with attacker-owned pks; the test still injects only one victim FK at a time.
