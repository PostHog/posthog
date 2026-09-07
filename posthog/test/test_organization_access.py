from django.core.cache import caches
from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.organization_access import (
    REACHABLE_METHODS,
    REVOCATION_MESSAGES,
    OrganizationAccessRevocation,
    RevokedOrganizationAccess,
    exclude_revoked_organizations,
    organization_access_revocation,
    organization_access_revocation_by_id,
    organization_access_revocation_for_team,
    organization_access_revocation_message,
)
from posthog.permissions import get_target_organization_from_view

DEACTIVATED = OrganizationAccessRevocation.DEACTIVATED
PENDING_DELETION = OrganizationAccessRevocation.PENDING_DELETION


class TestOrganizationAccessRevocation(SimpleTestCase):
    @parameterized.expand(
        [
            # Both columns are nullable, and null means "not set", so an organization that predates
            # either column keeps its access. A truthiness test on `is_active` would revoke these.
            ("null active, null pending deletion", None, None, None),
            ("null active", None, False, None),
            ("active", True, False, None),
            ("active, null pending deletion", True, None, None),
            ("deactivated", False, False, DEACTIVATED),
            ("deactivated, null pending deletion", False, None, DEACTIVATED),
            # Pending deletion outranks deactivation, which is what picks the app's redirect target.
            ("pending deletion", True, True, PENDING_DELETION),
            ("pending deletion and deactivated", False, True, PENDING_DELETION),
            ("pending deletion, null active", None, True, PENDING_DELETION),
        ]
    )
    def test_revocation_state(self, _name, is_active, is_pending_deletion, expected) -> None:
        organization = Organization(is_active=is_active, is_pending_deletion=is_pending_deletion)

        assert organization_access_revocation(organization) == expected

    def test_every_reachability_level_declares_its_methods(self) -> None:
        # A level added without an entry silently reaches nothing, so a viewset that declares it
        # would be closed instead of exempt.
        assert set(REACHABLE_METHODS) | {RevokedOrganizationAccess.ALL} == set(RevokedOrganizationAccess)

    def test_every_revocation_state_has_a_message(self) -> None:
        # A state added without a message raises a KeyError inside a denial, so every gate that
        # denies on it returns a 500 instead of a 403.
        assert set(REVOCATION_MESSAGES) == set(OrganizationAccessRevocation)

    @parameterized.expand(
        [
            (
                "deactivated with a reason",
                DEACTIVATED,
                "Unpaid balance.",
                "Your organization has been deactivated. Unpaid balance.",
            ),
            ("deactivated with a blank reason", DEACTIVATED, "   ", "Your organization has been deactivated."),
            ("deactivated with no reason", DEACTIVATED, None, "Your organization has been deactivated."),
            # The deactivation reason is not an explanation of a deletion, so it stays out of it.
            ("pending deletion", PENDING_DELETION, "Unpaid balance.", "Your organization is being deleted."),
        ]
    )
    def test_revocation_message(self, _name, revocation, reason, expected) -> None:
        organization = Organization(is_not_active_reason=reason)

        assert organization_access_revocation_message(revocation, organization) == expected


@override_settings(ORGANIZATION_ACCESS_CACHE_ENABLED=True)
class TestOrganizationAccessRevocationLookups(TestCase):
    def setUp(self) -> None:
        super().setUp()
        caches["organization_access"].clear()
        self.organization = Organization.objects.create(name="lookup org")
        self.team = self.organization.teams.create(name="lookup team")

    def test_a_saved_revocation_lands_on_the_next_lookup(self) -> None:
        # Prime the organization access cache, then revoke. The save has to invalidate the cache,
        # or every gate keeps admitting the organization until the entry expires.
        assert organization_access_revocation_by_id(self.organization.id) is None

        self.organization.is_active = False
        self.organization.save()

        assert organization_access_revocation_by_id(self.organization.id) == DEACTIVATED
        assert organization_access_revocation_for_team(self.team.id) == DEACTIVATED

    @parameterized.expand(
        [
            (
                "unknown organization",
                lambda: organization_access_revocation_by_id("00000000-0000-0000-0000-000000000000"),
            ),
            ("unknown team", lambda: organization_access_revocation_for_team(-1)),
        ]
    )
    def test_an_unresolvable_target_reports_no_revocation(self, _name, lookup) -> None:
        # Deliberate: a target that does not exist cannot have its access revoked, and the caller's
        # own lookup is what fails. Raising here would turn a deleted team into a 500 on the
        # billing gate instead of a 404 on the caller.
        assert lookup() is None


class TestTargetOrganizationResolution(TestCase):
    """`get_target_organization_from_view` backs three tenant boundaries that run on every
    authenticated API request, so it must not refetch a row the view already holds."""

    def setUp(self) -> None:
        super().setUp()
        organization = Organization.objects.create(name="resolver org")
        team = organization.teams.create(name="resolver team")
        self.team_id = team.id

    def _view(self, *, preload: bool):
        # Mirrors a project-scoped view: routing loads the team with `select_related`, while the
        # mixin's `organization` runs its own primary-key query because `_is_team_view` is false.
        queryset = Team.objects.select_related("organization") if preload else Team.objects
        team = queryset.get(id=self.team_id)

        class View:
            def __init__(self, team) -> None:
                self.team = team

            @property
            def organization(self) -> Organization:
                return Organization.objects.get(id=self.team.organization_id)

        return View(team)

    def test_a_preloaded_organization_costs_no_query(self) -> None:
        # Fails if the resolver reads `view.organization` before the team's foreign key, which
        # would add a query to every authenticated API request.
        view = self._view(preload=True)

        with self.assertNumQueries(0):
            organization = get_target_organization_from_view(view)

        assert organization is not None and organization.id == view.team.organization_id

    def test_it_still_resolves_when_the_organization_is_not_preloaded(self) -> None:
        view = self._view(preload=False)

        organization = get_target_organization_from_view(view)

        assert organization is not None and organization.id == view.team.organization_id

    def test_a_view_naming_no_organization_resolves_to_none(self) -> None:
        # A boundary treats None as nothing to gate, so this must not raise.
        assert get_target_organization_from_view(object()) is None


@override_settings(ORGANIZATION_ACCESS_CACHE_ENABLED=True)
class TestQuerysetRevocationFilter(TestCase):
    """The list filter and the scalar check are two readings of one rule, so they have to agree."""

    @parameterized.expand(
        [
            ("null active, null pending deletion", None, None),
            ("null active", None, False),
            ("active", True, False),
            ("active, null pending deletion", True, None),
            ("deactivated", False, False),
            ("deactivated, null pending deletion", False, None),
            ("pending deletion", True, True),
            ("pending deletion and deactivated", False, True),
            ("pending deletion, null active", None, True),
        ]
    )
    def test_the_queryset_filter_agrees_with_the_scalar_check(self, _name, is_active, is_pending_deletion) -> None:
        # Fails if either reading drifts on a nullable column. A row is visible in a list exactly
        # when a detail read of it is admitted, so a list cannot start disclosing what a detail
        # read denies, nor start hiding a healthy organization whose columns predate the migration.
        organization = Organization.objects.create(
            name="matrix org", is_active=is_active, is_pending_deletion=is_pending_deletion
        )
        team = organization.teams.create(name="matrix team")

        visible = exclude_revoked_organizations(Team.objects.filter(id=team.id)).exists()

        assert visible == (organization_access_revocation(organization) is None)
