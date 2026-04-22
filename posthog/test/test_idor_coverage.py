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

DISCOVERED_CASES: list[IDORTestCase] = discover_idor_test_cases()


def _case_params(case: IDORTestCase) -> tuple:
    # parameterized.expand requires tuples; name first so pytest test ids are readable
    return (case.name, case)


class TestAutomatedIDORCoverage(IDORTestMixin, APIBaseTest):
    """Auto-generated: one cross-team IDOR test per tenant-scoped viewset with a detail endpoint."""

    @parameterized.expand([_case_params(c) for c in DISCOVERED_CASES])
    def test_cross_team_get_detail(self, _name: str, case: IDORTestCase) -> None:
        """Attacker URL + victim resource id → 403/404/405, never 200."""
        try:
            instance = build_minimal_instance(case.model_cls, team=self.victim_team)
        except Exception as exc:
            self.skipTest(f"{case.model_cls.__name__}: could not auto-instantiate ({type(exc).__name__}: {exc})")

        # Determine which root-id to use. For /projects/, use attacker's project.
        # For /environments/, use attacker's team. For /organizations/, use attacker's org.
        if case.url.root == "projects":
            root_id: int | str = self.project.pk  # type: ignore[attr-defined]
        elif case.url.root == "environments":
            root_id = self.team.pk  # type: ignore[attr-defined]
        elif case.url.root == "organizations":
            root_id = str(self.organization.id)  # type: ignore[attr-defined]
        else:
            self.skipTest(f"Unknown URL root: {case.url.root}")

        # For nested-parent URLs, derive each intermediate id from the instance's FK.
        # E.g. parent_lookup_insight_id ⇒ instance.insight_id. Use attacker's pid/tid for
        # root; the intermediate id is the VICTIM's — this is the correct IDOR shape:
        # attacker's root, victim's nested ancestor, victim's leaf.
        intermediate_ids: dict[str, int | str] = {}
        for _, kwarg in case.url.intermediate_parents:
            field_name = kwarg.removeprefix("parent_lookup_")
            try:
                intermediate_ids[kwarg] = getattr(instance, field_name)
            except AttributeError:
                self.skipTest(
                    f"{case.name}: could not derive intermediate id {field_name!r} from {case.model_cls.__name__} instance"
                )

        # The URL's final kwarg may be `pk`, `id`, or something custom.
        # Prefer the named attribute off the instance; fall back to pk.
        pk_value = getattr(instance, case.url.pk_kwarg, instance.pk)
        url = case.url.build_url(  # type: ignore[attr-defined]
            root_id=root_id,
            pk=pk_value,
            intermediate_ids=intermediate_ids or None,
        )
        self.assertCrossTeamDenied(url, method="get")
