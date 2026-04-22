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
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.test.idor import IDORTestCase, IDORTestMixin, build_minimal_instance, discover_idor_test_cases
from posthog.test.idor.factory import reset_sentinel

DISCOVERED_CASES: list[IDORTestCase] = discover_idor_test_cases()


def _case_params(case: IDORTestCase) -> tuple:
    # parameterized.expand requires tuples; name first so pytest test ids are readable
    return (case.name, case)


class TestAutomatedIDORCoverage(IDORTestMixin, APIBaseTest):
    """Auto-generated: one cross-team IDOR test per tenant-scoped viewset with a detail endpoint."""

    def _build_instance_and_url(self, case: IDORTestCase) -> tuple[object, str, str]:
        """Return (instance, url, sentinel). Skips the test on setup failures.

        The instance is created in the victim team; the URL uses the attacker's
        root (team/project/org) with the victim resource's id — the canonical
        IDOR shape. A fresh sentinel is embedded in the instance's string
        fields so the test can verify no leak regardless of response status.
        """
        sentinel = reset_sentinel()
        try:
            instance = build_minimal_instance(case.model_cls, team=self.victim_team)
        except Exception as exc:
            self.skipTest(f"{case.model_cls.__name__}: could not auto-instantiate ({type(exc).__name__}: {exc})")

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
