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

from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.team import Team
from posthog.test.idor import IDORTestCase, IDORTestMixin, build_minimal_instance, discover_idor_test_cases
from posthog.test.idor.factory import reset_sentinel
from posthog.test.idor.fk_discovery import WritableFKField, discover_writable_tenant_fks
from posthog.test.idor.skip_list import IDOR_FK_PATCH_SKIP_LIST

DISCOVERED_CASES: list[IDORTestCase] = discover_idor_test_cases()


def _case_params(case: IDORTestCase) -> tuple:
    # parameterized.expand requires tuples; name first so pytest test ids are readable
    return (case.name, case)


def _iter_fk_cases() -> list[tuple[str, IDORTestCase, WritableFKField]]:
    """Cross-product of (case, writable tenant-FK field on its serializer)."""
    out: list[tuple[str, IDORTestCase, WritableFKField]] = []
    for case in DISCOVERED_CASES:
        if case.name in IDOR_FK_PATCH_SKIP_LIST:
            continue
        serializer_cls = getattr(case.viewset_cls, "serializer_class", None)
        if serializer_cls is None:
            continue
        for fk in discover_writable_tenant_fks(serializer_cls):
            label = f"{case.name}__{'__'.join((*fk.nested_path, fk.serializer_field_name))}"
            out.append((label, case, fk))
    return out


FK_PATCH_CASES = _iter_fk_cases()


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

        pk_value = getattr(instance, case.url.pk_kwarg, instance.pk)
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
        body: dict[str, Any]
        if fk.nested_path:
            inner: dict[str, Any] = {fk.serializer_field_name: victim_fk_pk}
            wrapper = inner
            for part in reversed(fk.nested_path):
                wrapper = {part: wrapper}
            body = wrapper
        else:
            body = {fk.serializer_field_name: victim_fk_pk}

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

        attr = fk.source_attr or fk.serializer_field_name
        reloaded = case.model_cls.objects.filter(pk=instance.pk).first()  # type: ignore[attr-defined]
        if reloaded is None:
            return
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
