"""
Automated cross-team IDOR coverage test.

Walks `posthog.api.router.urls` at collection time and generates one test
per tenant-scoped viewset with a detail endpoint. For each case:

  1. Build a minimal instance of the viewset's model in the VICTIM team
     (second org/team/user set up by `IDORTestMixin`).
  2. Log in as the attacker (`self.user` in `self.team`, from APIBaseTest).
  3. GET the detail URL on the **attacker's** team/project/org route with
     the **victim's** resource id.
  4. Assert the response is 403/404/405 (denied, not found, or method
     not supported) — never 200 with the victim's data.

This test is the foundation for IDOR coverage of all ~117 tenant-scoped
viewsets with detail endpoints. Viewsets whose models can't be
auto-instantiated (required FKs, custom validation) either get a fixture
override from `posthog/test/idor/fixtures.py` or are explicitly skipped.

Phase 5a adds `test_cross_tenant_fk_in_patch`, which targets a different
IDOR shape: the attacker hits **their own** resource's URL with a PATCH
body that smuggles a victim's FK pk into a writable FK field. A
vulnerable serializer (no team scoping on the queryset) accepts it,
binding the attacker's resource to the victim's record across tenant
boundaries.
"""

from __future__ import annotations

import warnings
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.team import Team
from posthog.test.idor import (
    IDORTestCase,
    IDORTestMixin,
    TenantRootCase,
    VictimContext,
    all_tenant_root_cases,
    build_minimal_instance,
    discover_idor_test_cases,
)
from posthog.test.idor.body_factory import BodyUnfillable, build_minimal_post_body
from posthog.test.idor.factory import reset_sentinel
from posthog.test.idor.fk_discovery import (
    ActionQueryParam,
    ActionSerializerCase,
    FilterParam,
    WritableFKField,
    discover_action_query_params,
    discover_action_serializers,
    discover_filter_params,
    discover_writable_tenant_fks,
)
from posthog.test.idor.skip_list import (
    IDOR_5XX_KNOWN_LATENT,
    IDOR_ACTION_SKIP_LIST,
    IDOR_FK_PATCH_SKIP_LIST,
    IDOR_FK_POST_SKIP_LIST,
)

DISCOVERED_CASES: list[IDORTestCase] = discover_idor_test_cases()


def _case_params(case: IDORTestCase) -> tuple:
    # parameterized.expand requires tuples; name first so pytest test ids are readable
    return (case.name, case)


def _scope_label(fk: WritableFKField) -> str:
    """Short tag distinguishing cross-org from cross-team in parametric test names.

    Both scopes run through the same fixture/test logic — the victim resource's
    tenancy is set by `build_minimal_instance` based on the FK's scope — but
    the label makes it obvious at a glance whether a failing test is a
    cross-team or cross-org IDOR.
    """
    return "org" if fk.scope in ("organization", "user_in_org") else "team"


def _iter_fk_cases() -> list[tuple[str, IDORTestCase, WritableFKField]]:
    """Cross-product of (case, writable tenant-FK field on its serializer).

    Create-only fields (in Meta.read_only_fields with an editable model FK)
    are excluded — DRF silently drops them from update bodies, so the runtime
    test cannot exercise them. The flag remains informational on the discovery
    record so the CI report can surface the count.
    """
    out: list[tuple[str, IDORTestCase, WritableFKField]] = []
    for case in DISCOVERED_CASES:
        if case.name in IDOR_FK_PATCH_SKIP_LIST:
            continue
        serializer_cls = getattr(case.viewset_cls, "serializer_class", None)
        if serializer_cls is None:
            continue
        for fk in discover_writable_tenant_fks(serializer_cls):
            if fk.is_create_only:
                continue
            label = f"{_scope_label(fk)}__{case.name}__{'__'.join((*fk.nested_path, fk.serializer_field_name))}"
            out.append((label, case, fk))
    return out


FK_PATCH_CASES = _iter_fk_cases()


def _iter_fk_post_cases() -> list[tuple[str, IDORTestCase, WritableFKField]]:
    """Same product as PATCH, minus viewsets explicitly skipped for POST.

    Create-only fields are excluded for the same reason as in PATCH — DRF
    drops the value from validated_data, so injection through the HTTP body
    can't reach the model layer. Bypassing DRF would require model.save()
    in tests, which is out of scope for the auto-IDOR framework.
    """
    out: list[tuple[str, IDORTestCase, WritableFKField]] = []
    for case in DISCOVERED_CASES:
        if case.name in IDOR_FK_PATCH_SKIP_LIST or case.name in IDOR_FK_POST_SKIP_LIST:
            continue
        serializer_cls = getattr(case.viewset_cls, "serializer_class", None)
        if serializer_cls is None:
            continue
        if not _viewset_supports_post(case.viewset_cls):
            continue
        for fk in discover_writable_tenant_fks(serializer_cls):
            if fk.is_create_only:
                continue
            label = f"{_scope_label(fk)}__{case.name}__{'__'.join((*fk.nested_path, fk.serializer_field_name))}"
            out.append((label, case, fk))
    return out


def _viewset_supports_post(viewset_cls: type) -> bool:
    """Heuristic — check whether the viewset's `create` is enabled.

    DRF generic viewsets expose `create` via `CreateModelMixin`; if the
    viewset overrides the method or the parent class strips it, POST will
    405. This is a fast filter; the test still skips on 5xx responses
    rather than asserting.
    """
    create = getattr(viewset_cls, "create", None)
    if create is None:
        return False
    # `http_method_names` is a DRF gate — if `post` isn't listed, the route doesn't exist.
    methods = [m.lower() for m in getattr(viewset_cls, "http_method_names", [])]
    if methods and "post" not in methods:
        return False
    return True


FK_POST_CASES = _iter_fk_post_cases()


def _iter_action_cases() -> list[tuple[str, IDORTestCase, ActionSerializerCase, str, WritableFKField]]:
    """Cross-product of (viewset case × @action × HTTP method × writable name-pattern field).

    Phase 5c — covers IDORs on custom @action endpoints with their own
    request body serializer (the `tom/dashboard-template` shape).

    Fans out per writable HTTP method so PUT/PATCH/POST variants of the
    same action each get a parametric case. GET is skipped because the
    body-injection shape doesn't apply to query-only requests.
    """
    out: list[tuple[str, IDORTestCase, ActionSerializerCase, str, WritableFKField]] = []
    writable_methods = {"POST", "PATCH", "PUT"}
    for case in DISCOVERED_CASES:
        for action in discover_action_serializers(case.viewset_cls):
            skip_key = f"{case.name}.{action.method_name}"
            if skip_key in IDOR_ACTION_SKIP_LIST:
                continue
            methods = tuple(m for m in action.http_methods if m in writable_methods)
            if not methods:
                continue
            for method in methods:
                for fk in discover_writable_tenant_fks(action.serializer_cls):
                    nested_label = "__".join((*fk.nested_path, fk.serializer_field_name))
                    label = f"{case.name}__{action.method_name}__{method}__{nested_label}__{fk.target_model.__name__}"
                    out.append((label, case, action, method, fk))
    return out


ACTION_CASES = _iter_action_cases()


def _iter_filter_param_cases() -> list[tuple[str, IDORTestCase, FilterParam]]:
    """Cross-product of (viewset case × filterset_fields entry pointing at a tenant-scoped model).

    Phase 6 — list-endpoint query-param IDORs (`?cohort=<victim_pk>`,
    `?dashboard__id=<victim_pk>`). Discovery only walks `filterset_fields`;
    `search_fields` are a different shape and not covered here.
    """
    out: list[tuple[str, IDORTestCase, FilterParam]] = []
    for case in DISCOVERED_CASES:
        for filter_param in discover_filter_params(case.viewset_cls):
            label = f"{case.name}__{filter_param.param_name}__{filter_param.target_model.__name__}"
            out.append((label, case, filter_param))
    return out


FILTER_PARAM_CASES = _iter_filter_param_cases()


def _iter_action_query_param_cases() -> list[tuple[str, IDORTestCase, ActionQueryParam, str]]:
    """Cross-product of (viewset case × @action × query param × HTTP method).

    Phase 6 — query-param IDORs on @action endpoints. Whereas
    `test_cross_tenant_id_in_action` injects a victim id into the
    request body, this parametric injects via the URL query string —
    different code paths in the action handler.
    """
    out: list[tuple[str, IDORTestCase, ActionQueryParam, str]] = []
    for case in DISCOVERED_CASES:
        for query_param in discover_action_query_params(case.viewset_cls):
            for method in query_param.http_methods:
                if method != "GET":
                    # Body-FK parametric already covers POST/PATCH/PUT actions
                    # (it inspects the request serializer); skip here to avoid
                    # double-counting.
                    continue
                label = (
                    f"{case.name}__{query_param.method_name}__{method}__"
                    f"{query_param.param_name}__{query_param.target_model.__name__}"
                )
                out.append((label, case, query_param, method))
    return out


ACTION_QUERY_PARAM_CASES = _iter_action_query_param_cases()


def _tenant_root_params() -> list[tuple[str, TenantRootCase]]:
    """Parametric input for the cross-tenant-root test."""
    return [(case.name, case) for case in all_tenant_root_cases()]


TENANT_ROOT_CASES = _tenant_root_params()


class TestAutomatedIDORCoverage(IDORTestMixin, APIBaseTest):
    """Auto-generated: one cross-team IDOR test per tenant-scoped viewset with a detail endpoint."""

    def _build_instance_and_url(
        self,
        case: IDORTestCase,
        team_for_instance: Team | None = None,
    ) -> tuple[object, str, str]:
        """Return (instance, url, sentinel). Skips the test on setup failures.

        By default the instance lives in the victim team and the URL uses the
        attacker's root — the canonical cross-team IDOR shape (attacker hits
        victim's resource via their own root URL).

        When `team_for_instance` is supplied (Phase 5a FK-PATCH variant), the
        instance lives in that team and the URL uses *that team's* root, so
        the attacker can reach their own resource and PATCH it. A fresh
        sentinel is embedded in the instance's string fields so the test can
        verify no leak regardless of response status.
        """
        sentinel = reset_sentinel()
        instance_team = team_for_instance if team_for_instance is not None else self.victim_team
        try:
            instance = build_minimal_instance(case.model_cls, team=instance_team)
        except Exception as exc:
            self.skipTest(f"{case.model_cls.__name__}: could not auto-instantiate ({type(exc).__name__}: {exc})")

        # URL root always uses the attacker's tenant. For cross-team
        # GET/PATCH/DELETE that combines with a victim-team instance pk to
        # express the canonical "attacker reaches victim's resource via their
        # own URL" shape; for the FK-in-PATCH variant the instance is in the
        # attacker's team and so the URL hits a real, owned resource.
        if case.url.root == "projects":
            root_id: int | str = self.project.pk  # type: ignore[attr-defined]
        elif case.url.root == "environments":
            root_id = self.team.pk  # type: ignore[attr-defined]
        elif case.url.root == "organizations":
            root_id = str(self.organization.id)  # type: ignore[attr-defined]
        else:
            self.skipTest(f"Unknown URL root: {case.url.root}")

        intermediate_ids: dict[str, int | str] = {}
        for _, kwarg in case.url.intermediate_parents:
            field_name = kwarg.removeprefix("parent_lookup_")
            try:
                intermediate_ids[kwarg] = getattr(instance, field_name)
            except AttributeError:
                self.skipTest(
                    f"{case.name}: could not derive intermediate id {field_name!r} from {case.model_cls.__name__} instance"
                )

        pk_value = _read_lookup_value(instance, case.url.pk_kwarg)
        url = case.url.build_url(  # type: ignore[attr-defined]
            root_id=root_id,
            pk=pk_value,
            intermediate_ids=intermediate_ids or None,
        )
        return instance, url, sentinel

    @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
    def test_cross_team_get_detail(self, _name: str, case: IDORTestCase) -> None:
        """Attacker hits victim resource URL → 403/404/405 + no sentinel leak."""
        _instance, url, sentinel = self._build_instance_and_url(case)
        response = self.assertCrossTeamDenied(url, method="get")
        self.assertSentinelNotLeaked(response, sentinel)

    @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
    def test_cross_team_patch_detail(self, _name: str, case: IDORTestCase) -> None:
        """Attacker cannot mutate a cross-team resource + no sentinel leak."""
        instance, url, sentinel = self._build_instance_and_url(case)
        response = self.assertCrossTeamDenied(
            url, method="patch", data={"name": "pwned", "title": "pwned", "description": "pwned"}
        )
        self.assertSentinelNotLeaked(response, sentinel)
        # Verify the victim's resource is unchanged (reload from DB and check sentinel still in name).
        _assert_resource_unchanged(self, case, instance, sentinel)

    @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
    def test_cross_team_delete_detail(self, _name: str, case: IDORTestCase) -> None:
        """Attacker cannot delete a cross-team resource + no sentinel leak."""
        instance, url, sentinel = self._build_instance_and_url(case)
        response = self.assertCrossTeamDenied(url, method="delete")
        self.assertSentinelNotLeaked(response, sentinel)
        # Hard-delete check: resource must still exist in the victim team.
        assert case.model_cls.objects.filter(pk=instance.pk).exists(), (  # type: ignore[attr-defined]
            f"IDOR: DELETE {url} actually removed the victim's {case.model_cls.__name__}"
        )

    @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
    def test_cross_team_put_detail(self, _name: str, case: IDORTestCase) -> None:
        """Attacker cannot replace a cross-team resource via PUT + no sentinel leak.

        PUT and PATCH can branch through different validation paths in DRF — a
        viewset with overridden update() may scope correctly on partial
        updates but not on full ones.
        """
        instance, url, sentinel = self._build_instance_and_url(case)
        serializer_cls = getattr(case.viewset_cls, "serializer_class", None)
        body: dict[str, Any] = {"name": "pwned", "title": "pwned", "description": "pwned"}
        if serializer_cls is not None:
            try:
                body = build_minimal_post_body(serializer_cls, team=self.team)  # type: ignore[attr-defined]
            except Exception:
                # Fall back to the partial-update body — endpoints that allow
                # partial PUTs still get exercised; strict-PUT endpoints will
                # 400 (still a valid denial of the cross-team write).
                pass
        response = self.assertCrossTeamDenied(url, method="put", data=body)
        self.assertSentinelNotLeaked(response, sentinel)
        _assert_resource_unchanged(self, case, instance, sentinel)

    @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
    def test_cross_team_list_isolation(self, _name: str, case: IDORTestCase) -> None:
        """Listing on attacker's tenant must not include victim's resource.

        Detail parametrics catch unscoped retrieve(); a queryset that's
        missing team_id on list() leaks entire collections, not single
        records. Build a victim resource, hit the attacker's list URL, and
        assert the victim's pk and sentinel are absent from the response.
        """
        sentinel = reset_sentinel()
        try:
            victim_instance = build_minimal_instance(case.model_cls, team=self.victim_team)  # type: ignore[attr-defined]
        except Exception as exc:
            self.skipTest(f"{case.model_cls.__name__}: could not build victim ({type(exc).__name__}: {exc})")

        list_url = self._build_list_url_for_attacker(case)
        if list_url is None:
            return  # skipTest already called

        response = self.client.get(list_url)  # type: ignore[attr-defined]
        if response.status_code >= 500:
            _maybe_warn_5xx(case.name, response.status_code)
            return
        if response.status_code not in range(200, 300):
            return  # 401/403/404 acceptable — denial is the safe path

        self.assertSentinelNotLeaked(response, sentinel)

        try:
            payload = response.json()
        except Exception:
            return
        if isinstance(payload, list):
            results = payload
        elif isinstance(payload, dict):
            results = payload.get("results", [])
        else:
            return
        if not isinstance(results, list):
            return

        victim_pk = str(victim_instance.pk)
        for row in results:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id") or row.get("pk")
            if row_id is not None and str(row_id) == victim_pk:
                raise AssertionError(
                    f"IDOR list leak: {list_url} returned victim {case.model_cls.__name__}(pk={victim_pk})"
                )

    @parameterized.expand(FILTER_PARAM_CASES)
    def test_cross_tenant_filter_param(
        self,
        _name: str,
        case: IDORTestCase,
        filter_param: FilterParam,
    ) -> None:
        """Attacker cannot use `?<filter>=<victim_pk>` to enumerate cross-tenant rows.

        DRF's `filterset_fields` accept query params that become ORM filters.
        If the underlying queryset isn't tenant-scoped, the filter happily
        joins across tenants and returns the victim's records. The runtime
        check parses the JSON results and asserts the victim's pk and
        sentinel are absent.
        """
        sentinel = reset_sentinel()
        try:
            victim_instance = build_minimal_instance(filter_param.target_model, team=self.victim_team)  # type: ignore[attr-defined]
        except Exception as exc:
            self.skipTest(
                f"{case.name}.{filter_param.param_name}: could not build victim "
                f"{filter_param.target_model.__name__} ({type(exc).__name__}: {exc})"
            )

        list_url = self._build_list_url_for_attacker(case)
        if list_url is None:
            return  # skipTest already called

        sep = "&" if "?" in list_url else "?"
        url = f"{list_url}{sep}{filter_param.param_name}={victim_instance.pk}"
        response = self.client.get(url)  # type: ignore[attr-defined]
        if response.status_code >= 500:
            _maybe_warn_5xx(case.name, response.status_code)
            return
        if response.status_code not in range(200, 300):
            return  # 400/401/403/404 acceptable

        self.assertSentinelNotLeaked(response, sentinel)

        try:
            payload = response.json()
        except Exception:
            return
        if isinstance(payload, list):
            results = payload
        elif isinstance(payload, dict):
            results = payload.get("results", [])
        else:
            return
        if not isinstance(results, list):
            return

        victim_pk = str(victim_instance.pk)
        for row in results:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id") or row.get("pk")
            if row_id is not None and str(row_id) == victim_pk:
                raise AssertionError(
                    f"IDOR filter leak: {url} returned a row whose id matches "
                    f"victim {filter_param.target_model.__name__}(pk={victim_pk})"
                )

    @parameterized.expand(TENANT_ROOT_CASES)
    def test_cross_org_root_access(self, _name: str, case: TenantRootCase) -> None:
        """Attacker cannot reach a victim's org/project/team root URL.

        For tenant-root viewsets the URL itself identifies the victim
        (e.g. `/api/organizations/<victim_org_uuid>/`). Permission classes
        — OrganizationMemberPermissions, project membership, etc. — must
        reject every method (GET / PATCH / DELETE). Any 2xx response is
        an IDOR; the sentinel-leak check guards info-leaks in error
        bodies.
        """
        victim = VictimContext(
            org_uuid=str(self.victim_org.id),  # type: ignore[attr-defined]
            project_pk=self.victim_project.pk,  # type: ignore[attr-defined]
            team_pk=self.victim_team.pk,  # type: ignore[attr-defined]
        )
        url = case.build_url(victim)

        # GET — most common attack shape.
        response = self.assertCrossOrgDenied(url, method="get")
        # The victim's org/project/team has no string sentinel embedded
        # by `build_minimal_instance`; we still leak-check the response
        # for the victim's UUID/name as a defence-in-depth signal.
        self.assertSentinelNotLeaked(response, victim.org_uuid)

        # PATCH — block mutations across tenant boundaries.
        patch_response = self.assertCrossOrgDenied(url, method="patch", data={"name": "pwned", "title": "pwned"})
        self.assertSentinelNotLeaked(patch_response, victim.org_uuid)

        # DELETE — block tenant-root deletion across boundaries. Some
        # viewsets disallow DELETE entirely (405); that's still a denial.
        delete_response = self.assertCrossOrgDenied(url, method="delete")
        self.assertSentinelNotLeaked(delete_response, victim.org_uuid)

    @parameterized.expand(ACTION_CASES)
    def test_cross_tenant_id_in_action(
        self,
        _name: str,
        case: IDORTestCase,
        action: ActionSerializerCase,
        method: str,
        fk: WritableFKField,
    ) -> None:
        """Attacker cannot smuggle a victim's tenant id into a custom @action body.

        Phase 5c — covers @action endpoints with their own request
        serializer (the tom/dashboard-template shape). The runtime checks
        are softer than for vanilla POST/PATCH because action semantics
        vary; we treat 4xx as pass, 5xx as skip-loud, and rely on
        sentinel-leak detection on 2xx response bodies.

        One parametric case per (viewset, action, method, fk) — different
        HTTP methods may take subtly different validation paths.
        """

        # 1. Build victim resource FIRST with a distinct sentinel so the
        #    later attacker-side resources don't share it (which would
        #    cause the leak check to fire on the attacker's own data).
        victim_sentinel = reset_sentinel()
        try:
            victim_resource = build_minimal_instance(fk.target_model, team=self.victim_team)
        except Exception as exc:
            self.skipTest(
                f"{case.name}.{action.method_name}.{fk.serializer_field_name}: could not build victim "
                f"{fk.target_model.__name__} ({type(exc).__name__}: {exc})"
            )

        # 2. Reset sentinel so attacker resources + body get a different one.
        reset_sentinel()

        # 3. Synthesize the action's body for the attacker's team.
        try:
            body = build_minimal_post_body(action.serializer_cls, team=self.team)
        except BodyUnfillable as exc:
            self.skipTest(f"{case.name}.{action.method_name}.{fk.serializer_field_name}: body unfillable ({exc})")
        except Exception as exc:
            self.skipTest(
                f"{case.name}.{action.method_name}.{fk.serializer_field_name}: body error ({type(exc).__name__}: {exc})"
            )

        # 4. Inject the victim lookup value into the body. Nested action
        #    serializer fields (e.g. `body.request.dashboard_id`) are
        #    wrapped via `_inject_fk_into_body`, which mirrors the PATCH
        #    variant. `fk.lookup_attr` is `pk` for standard FK shapes;
        #    string-by-name patterns use `key`/`short_id` instead.
        try:
            victim_value = getattr(victim_resource, fk.lookup_attr)
        except AttributeError:
            self.skipTest(
                f"{case.name}.{action.method_name}.{fk.serializer_field_name}: "
                f"victim {fk.target_model.__name__} has no attribute {fk.lookup_attr!r}"
            )
        body = _inject_fk_into_body(body, fk, str(victim_value))

        # 5. Build the action URL on the attacker's tenant root. For
        #    detail-route actions, build an attacker-owned instance to anchor the URL.
        try:
            action_url = self._build_action_url_for_attacker(case, action)
        except Exception as exc:
            self.skipTest(f"{case.name}.{action.method_name}.{fk.serializer_field_name}: URL build failed ({exc})")

        # 6. Invoke.
        client_method = getattr(self.client, method.lower())  # type: ignore[attr-defined]
        response = client_method(action_url, data=body, format="json")

        # 7. Pass cases:
        #    - 5xx: latent server bug — warn unless explicitly listed as
        #      known-latent, and still leak-check the response (a partial
        #      handler may have read the victim before crashing).
        #    - non-2xx: rejected somewhere in the action's chain. Pass.
        #    - 2xx: action proceeded. Sentinel-leak-check the response body
        #      against the victim's sentinel — if it appears, the action
        #      pulled in the victim's data despite the cross-tenant id.
        if response.status_code >= 500:
            _maybe_warn_5xx(f"{case.name}.{action.method_name}", response.status_code)
            self.assertSentinelNotLeaked(response, victim_sentinel)
            return
        if response.status_code not in range(200, 300):
            return
        self.assertSentinelNotLeaked(response, victim_sentinel)

    @parameterized.expand(ACTION_QUERY_PARAM_CASES)
    def test_cross_tenant_id_in_action_query_param(
        self,
        _name: str,
        case: IDORTestCase,
        query_param: ActionQueryParam,
        method: str,
    ) -> None:
        """Attacker cannot smuggle a victim's tenant id via an @action's query string.

        Companion to `test_cross_tenant_id_in_action`. That parametric
        injects victim ids into the **request body** (POST/PATCH/PUT
        actions); this one injects via the **query string** of GET
        actions, which take a different validation path.
        """
        victim_sentinel = reset_sentinel()
        try:
            victim_resource = build_minimal_instance(query_param.target_model, team=self.victim_team)
        except Exception as exc:
            self.skipTest(
                f"{case.name}.{query_param.method_name}.{query_param.param_name}: "
                f"could not build victim {query_param.target_model.__name__} ({type(exc).__name__}: {exc})"
            )

        try:
            action_url = self._build_action_url_for_attacker(case, query_param)
        except Exception as exc:
            self.skipTest(f"{case.name}.{query_param.method_name}.{query_param.param_name}: URL build failed ({exc})")

        sep = "&" if "?" in action_url else "?"
        url = f"{action_url}{sep}{query_param.param_name}={victim_resource.pk}"
        client_method = getattr(self.client, method.lower())  # type: ignore[attr-defined]
        response = client_method(url)

        if response.status_code >= 500:
            _maybe_warn_5xx(f"{case.name}.{query_param.method_name}", response.status_code)
            self.assertSentinelNotLeaked(response, victim_sentinel)
            return
        if response.status_code not in range(200, 300):
            return
        self.assertSentinelNotLeaked(response, victim_sentinel)

    def _build_action_url_for_attacker(
        self,
        case: IDORTestCase,
        action: ActionSerializerCase | ActionQueryParam,
    ) -> str:
        """Build a URL for `action` on `case`'s viewset, on the attacker's tenant root."""
        if case.url.root == "projects":
            root_id: int | str = self.project.pk  # type: ignore[attr-defined]
        elif case.url.root == "environments":
            root_id = self.team.pk  # type: ignore[attr-defined]
        elif case.url.root == "organizations":
            root_id = str(self.organization.id)  # type: ignore[attr-defined]
        else:
            raise ValueError(f"Unknown URL root: {case.url.root}")

        intermediate_ids: dict[str, int | str] = {}
        for _, kwarg in case.url.intermediate_parents:
            field_name = kwarg.removeprefix("parent_lookup_")
            parent_model = _resolve_intermediate_parent_model(case.model_cls, field_name)
            if parent_model is None:
                raise ValueError(f"intermediate parent {field_name!r} can't be resolved")
            parent_instance = build_minimal_instance(parent_model, team=self.team)
            intermediate_ids[kwarg] = parent_instance.pk

        if action.detail:
            attacker_instance = build_minimal_instance(case.model_cls, team=self.team)
            return case.url.build_action_url(  # type: ignore[attr-defined]
                root_id=root_id,
                pk=attacker_instance.pk,
                action_url_path=action.url_path,
                intermediate_ids=intermediate_ids or None,
            )
        return case.url.build_action_url(  # type: ignore[attr-defined]
            root_id=root_id,
            action_url_path=action.url_path,
            intermediate_ids=intermediate_ids or None,
        )

    @parameterized.expand(FK_POST_CASES)
    def test_cross_tenant_fk_in_post(
        self,
        _name: str,
        case: IDORTestCase,
        fk: WritableFKField,
    ) -> None:
        """Attacker cannot smuggle a victim's tenant FK into a NEW resource via POST."""
        # 1. Synthesize a body that should pass validation in attacker's team.
        try:
            body = build_minimal_post_body(case.viewset_cls.serializer_class, team=self.team)
        except BodyUnfillable as exc:
            self.skipTest(f"{case.name}.{fk.serializer_field_name}: body unfillable ({exc})")
        except Exception as exc:
            self.skipTest(f"{case.name}.{fk.serializer_field_name}: body error ({type(exc).__name__}: {exc})")

        # 2. Build the victim FK target.
        try:
            victim_fk = build_minimal_instance(fk.target_model, team=self.victim_team)
        except Exception as exc:
            self.skipTest(
                f"{case.name}.{fk.serializer_field_name}: could not build victim "
                f"{fk.target_model.__name__} ({type(exc).__name__}: {exc})"
            )

        victim_fk_pk: Any = victim_fk.pk

        # 3. Inject the victim FK into the body, replacing whatever the
        #    synthesizer chose. M2M wraps in a list to match DRF semantics.
        scalar: Any = [victim_fk_pk] if fk.is_many else victim_fk_pk
        body = _inject_fk_into_body(body, fk, scalar)

        # 4. Build list URL on the attacker's tenant root.
        list_url = self._build_list_url_for_attacker(case)
        if list_url is None:
            return  # skipTest already called

        response = self.client.post(list_url, data=body, format="json")  # type: ignore[attr-defined]

        # 5. Outcomes:
        #    - 5xx: latent bug, warn (unless known-latent) and stop — we
        #      can't tell whether the FK landed before the crash, so the
        #      reloaded-row check below is unreliable.
        #    - non-2xx: validation rejected. Pass.
        #    - 2xx + reloaded created instance has FK pointing at victim_pk: IDOR.
        if response.status_code >= 500:
            _maybe_warn_5xx(case.name, response.status_code)
            return
        if response.status_code not in range(200, 300):
            return
        if fk.nested_path:
            return  # nested verification needs case-specific knowledge

        try:
            payload = response.json()
            created_id = payload.get("id") or payload.get("pk")
        except Exception:
            return
        if created_id is None:
            return
        try:
            created = case.model_cls.objects.filter(pk=created_id).first()  # type: ignore[attr-defined]
        except Exception:
            return
        if created is None:
            return

        if fk.is_many:
            _assert_m2m_does_not_contain_victim(created, fk, victim_fk_pk, list_url, case)
        else:
            _assert_single_fk_not_bound_to_victim(created, fk, victim_fk_pk, list_url, case)

    def _build_list_url_for_attacker(self, case: IDORTestCase) -> str | None:
        """Construct the list URL on the attacker's tenant root for POST.

        Skips the test when the URL has intermediate parents that would
        require victim-side context to resolve.
        """
        if case.url.root == "projects":
            root_id: int | str = self.project.pk  # type: ignore[attr-defined]
        elif case.url.root == "environments":
            root_id = self.team.pk  # type: ignore[attr-defined]
        elif case.url.root == "organizations":
            root_id = str(self.organization.id)  # type: ignore[attr-defined]
        else:
            self.skipTest(f"Unknown URL root: {case.url.root}")
            return None

        intermediate_ids: dict[str, int | str] = {}
        for _, kwarg in case.url.intermediate_parents:
            field_name = kwarg.removeprefix("parent_lookup_")
            # Build the intermediate parent in the attacker's team so the URL
            # resolves to a real owned resource. If we can't build it, skip.
            parent_model = _resolve_intermediate_parent_model(case.model_cls, field_name)
            if parent_model is None:
                self.skipTest(f"{case.name}: cannot resolve intermediate parent model for {field_name!r}")
                return None
            try:
                parent_instance = build_minimal_instance(parent_model, team=self.team)
            except Exception as exc:
                self.skipTest(
                    f"{case.name}: could not build intermediate parent {parent_model.__name__} "
                    f"({type(exc).__name__}: {exc})"
                )
                return None
            intermediate_ids[kwarg] = parent_instance.pk

        return case.url.build_list_url(root_id=root_id, intermediate_ids=intermediate_ids or None)  # type: ignore[attr-defined]

    @parameterized.expand(FK_PATCH_CASES)
    def test_cross_tenant_fk_in_patch(
        self,
        _name: str,
        case: IDORTestCase,
        fk: WritableFKField,
    ) -> None:
        """Attacker cannot smuggle a victim's tenant FK into their own resource via PATCH."""
        # 1. Attacker's own resource — they're allowed to PATCH this normally.
        instance, url, _sentinel = self._build_instance_and_url(case, team_for_instance=self.team)

        # 2. Victim FK target. Always scope by the victim team; the registered
        #    fixtures handle the org/user-scoped cases via team.organization /
        #    _victim_user().
        try:
            victim_fk = build_minimal_instance(fk.target_model, team=self.victim_team)
        except Exception as exc:
            self.skipTest(
                f"{case.name}.{fk.serializer_field_name}: could not build victim "
                f"{fk.target_model.__name__} ({type(exc).__name__}: {exc})"
            )

        victim_fk_pk: Any = victim_fk.pk

        # 3. PATCH body — top-level keys map directly; nested keys wrap once.
        #    M2M fields take a list (DRF replaces the set on PATCH).
        scalar_value: Any = [victim_fk_pk] if fk.is_many else victim_fk_pk
        body: dict[str, Any]
        if fk.nested_path:
            inner: dict[str, Any] = {fk.serializer_field_name: scalar_value}
            wrapper = inner
            for part in reversed(fk.nested_path):
                wrapper = {part: wrapper}
            body = wrapper
        else:
            body = {fk.serializer_field_name: scalar_value}

        response = self.client.patch(url, data=body, format="json")  # type: ignore[attr-defined]

        # 4. Pass cases:
        #    - Non-2xx: validation rejected, perm check failed, etc. — denied.
        #    - 2xx but FK actually wasn't written (silently dropped). Some
        #      serializers accept extra keys without applying them.
        #    Fail case: 2xx AND the FK on the reloaded instance equals the
        #    victim's pk (cross-tenant FK binding succeeded).
        if response.status_code not in range(200, 300):
            return
        if fk.nested_path:
            # Verifying the FK landed on a related object requires per-case
            # knowledge of how the nested update is applied. The 2xx response
            # is a softer signal than for top-level fields; we rely on the
            # status code alone here.
            return

        reloaded = case.model_cls.objects.filter(pk=instance.pk).first()  # type: ignore[attr-defined]
        if reloaded is None:
            return

        if fk.is_many:
            _assert_m2m_does_not_contain_victim(reloaded, fk, victim_fk_pk, url, case)
            return

        _assert_single_fk_not_bound_to_victim(reloaded, fk, victim_fk_pk, url, case)


def _read_lookup_value(instance: object, kwarg: str) -> Any:
    """Read the URL lookup value from an instance, supporting joined attrs.

    For `user__uuid` we walk `instance.user.uuid`; for plain `pk` / `short_id`
    we read the attribute directly. Falls back to `instance.pk` if the chain
    has a None along the way (an attribute we can't resolve) so the URL build
    still produces a string DRF can parse.
    """
    current: Any = instance
    for segment in kwarg.split("__"):
        if current is None:
            return getattr(instance, "pk", None)
        current = getattr(current, segment, None)
    if current is None:
        return getattr(instance, "pk", None)
    return current


def _maybe_warn_5xx(key: str, status_code: int) -> None:
    """Emit a warning for an unexplained 5xx unless the case is in
    `IDOR_5XX_KNOWN_LATENT`. The caller still runs leak detection — this
    only controls whether the test surface flags the response as suspicious.
    """
    if key in IDOR_5XX_KNOWN_LATENT:
        return
    warnings.warn(
        f"IDOR test received {status_code} for {key}; treating as pass but the "
        f"response should be inspected — a partial handler may have read victim "
        f"data before crashing. Add to IDOR_5XX_KNOWN_LATENT once understood.",
        stacklevel=3,
    )


def _inject_fk_into_body(body: dict[str, Any], fk: WritableFKField, value: Any) -> dict[str, Any]:
    """Set the victim FK at the right depth, mutating a copy of `body`."""
    body = dict(body)
    if not fk.nested_path:
        body[fk.serializer_field_name] = value
        return body
    cursor = body
    *path_to_last, last = fk.nested_path
    for segment in path_to_last:
        nested = dict(cursor.get(segment) or {})
        cursor[segment] = nested
        cursor = nested
    inner = dict(cursor.get(last) or {})
    inner[fk.serializer_field_name] = value
    cursor[last] = inner
    return body


def _resolve_intermediate_parent_model(model_cls: type, parent_attr_name: str) -> type | None:
    """Find the FK target model for an intermediate URL parent.

    The viewset's URL like `/api/environments/<team_id>/batch_exports/<batch_export_id>/runs/<pk>/`
    has `batch_export` as an intermediate parent. The corresponding model
    field is `BatchExportRun.batch_export`, a ForeignKey. We resolve it
    so the test can build a parent instance in the attacker's team.
    """
    try:
        meta_field = model_cls._meta.get_field(parent_attr_name)  # type: ignore[attr-defined]
    except Exception:
        return None
    related = getattr(meta_field, "related_model", None)
    if isinstance(related, type):
        return related
    return None


def _assert_single_fk_not_bound_to_victim(
    reloaded: object,
    fk: WritableFKField,
    victim_fk_pk: Any,
    url: str,
    case: IDORTestCase,
) -> None:
    """For top-level single-FK PATCH: reload, fetch the FK attr, compare to victim pk."""
    attr = fk.source_attr or fk.serializer_field_name
    try:
        actual = getattr(reloaded, attr + "_id", None) or getattr(reloaded, attr, None)
    except Exception:
        actual = None
    if actual is None:
        return
    if hasattr(actual, "pk"):
        actual = actual.pk
    if actual == victim_fk_pk:
        raise AssertionError(
            f"IDOR: PATCH {url} bound attacker's {case.model_cls.__name__}.{attr} "
            f"to victim's {fk.target_model.__name__}(pk={victim_fk_pk}) — "
            f"writable FK accepted across tenant boundary"
        )


def _assert_m2m_does_not_contain_victim(
    reloaded: object,
    fk: WritableFKField,
    victim_fk_pk: Any,
    url: str,
    case: IDORTestCase,
) -> None:
    """For M2M PATCH: reload, walk the related manager, fail if victim pk landed in the set."""
    attr = fk.source_attr or fk.serializer_field_name
    related_manager = getattr(reloaded, attr, None)
    if related_manager is None:
        return
    try:
        linked_pks = set(related_manager.values_list("pk", flat=True))
    except Exception:
        return
    if victim_fk_pk in linked_pks:
        raise AssertionError(
            f"IDOR: PATCH {url} added victim's {fk.target_model.__name__}(pk={victim_fk_pk}) "
            f"to attacker's {case.model_cls.__name__}.{attr} M2M set — "
            f"writable many=True FK accepted across tenant boundary"
        )


def _assert_resource_unchanged(test_case: object, case: IDORTestCase, instance: object, sentinel: str) -> None:
    """Verify a PATCH didn't mutate the victim's resource.

    The attacker's PATCH payload sent `name=pwned`, `title=pwned`, `description=pwned`.
    Reloading the instance, at least one of those fields should still contain the
    sentinel (if it was embedded there during creation). If ALL three are missing
    AND the sentinel is absent from the reloaded instance, we can't reliably verify
    — skip the mutation check.
    """
    _ = sentinel  # reserved for future refinement
    reloaded = case.model_cls.objects.filter(pk=instance.pk).first()  # type: ignore[attr-defined]
    assert reloaded is not None, f"victim's {case.model_cls.__name__} was unexpectedly deleted"
    for field_name in ("name", "title", "description"):
        if hasattr(reloaded, field_name):
            val = getattr(reloaded, field_name)
            if val == "pwned":
                raise AssertionError(
                    f"IDOR: PATCH {case.name} mutated victim's {field_name} to 'pwned' (instance {instance.pk})"  # type: ignore[attr-defined]
                )
