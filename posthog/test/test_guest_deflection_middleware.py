from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.guest_grants import create_grant

from products.notebooks.backend.models import Notebook


class TestGuestDeflectionMiddleware(APIBaseTest):
    """HTTP-level coverage of the guest deflection rules.

    Setup wires up:
    - one guest user with an optional grant list
    - one granted notebook + one ungranted notebook as a foil
    """

    def setUp(self) -> None:
        super().setUp()
        # Advanced permissions feature is required for the UserAccessControl layer to honor
        # per-object AC rows. Without it the AC layer short-circuits and guests look no
        # different from members without grants.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        self.granted_notebook = Notebook.objects.create(team=self.team, title="Granted", short_id="GRNT0001")
        self.ungranted_notebook = Notebook.objects.create(team=self.team, title="Ungranted", short_id="HIDD0001")

    def _login_guest(self) -> None:
        self.client.force_login(self.guest_user)

    def _login_regular(self) -> None:
        self.client.force_login(self.user)

    def _grant_notebook(self) -> None:
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.granted_notebook.short_id,
            created_by=self.user,
        )

    def test_non_guest_user_is_never_deflected(self) -> None:
        self._login_regular()
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.ungranted_notebook.short_id}/")
        self.assertNotEqual(res.status_code, 404)

    def test_guest_user_without_grants_is_deflected_from_api(self) -> None:
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.ungranted_notebook.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_guest_user_without_grants_is_redirected_on_spa_route(self) -> None:
        # `?from=login` is appended so the landing scene knows this is a system-driven
        # deflection — single-grant guests auto-jump to their resource on this kind of
        # redirect; explicit header navigation (no flag) shows the list.
        self._login_guest()
        res = self.client.get(f"/project/{self.team.pk}/experiments", follow=False)
        self.assertEqual(res.status_code, status.HTTP_302_FOUND)
        self.assertEqual(res["Location"], "/guest?from=login")

    def test_guest_landing_page_is_not_deflected(self) -> None:
        self._login_guest()
        res = self.client.get("/guest", follow=False)
        self.assertNotEqual(res.status_code, status.HTTP_302_FOUND)

    def test_themes_metadata_is_allowed_for_guest_with_any_grant(self) -> None:
        self._grant_notebook()
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/data_color_themes/")
        self.assertNotEqual(res.status_code, 404)

    def test_themes_metadata_post_is_deflected(self) -> None:
        self._grant_notebook()
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/data_color_themes/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_users_me_is_always_allowed(self) -> None:
        self._login_guest()
        res = self.client.get("/api/users/@me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_organizations_current_is_always_allowed(self) -> None:
        self._login_guest()
        res = self.client.get("/api/organizations/@current/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("annotations", "projects"),
            ("cohorts", "projects"),
            ("tags", "projects"),
            ("insight_variables", "environments"),
            ("quick_filters", "environments"),
            ("data_color_themes", "environments"),
        ]
    )
    def test_metadata_endpoints_require_any_grant(self, endpoint: str, scope: str) -> None:
        self._login_guest()
        url = f"/api/{scope}/{self.team.pk}/{endpoint}/"
        res_without_grant = self.client.get(url)
        self.assertEqual(res_without_grant.status_code, status.HTTP_404_NOT_FOUND)

        self._grant_notebook()
        res_with_grant = self.client.get(url)
        self.assertNotEqual(res_with_grant.status_code, 404)


class TestGuestDeflectionCrossOrgScoping(APIBaseTest):
    """Guest deflection must scope to the org the request targets.

    A user who is a guest of org A AND a regular member of org B must NOT be
    deflected on org B's paths — guest behavior only applies in the org where
    they are actually a guest.
    """

    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(is_guest=True)
        from posthog.models import Organization, Team

        self.org_b = Organization.objects.create(name="Org B")
        OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.user,
            is_guest=False,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.team_b = Team.objects.create_with_data(organization=self.org_b, name="Team B", initiating_user=self.user)
        self.notebook_b = Notebook.objects.create(team=self.team_b, title="Org B notebook", short_id="ORGB0001")

    def test_guest_in_other_org_is_not_deflected_on_target_org_paths(self) -> None:
        self.client.force_login(self.user)
        res = self.client.get(f"/api/projects/{self.team_b.pk}/notebooks/{self.notebook_b.short_id}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_guest_in_same_org_is_deflected_on_ungranted_paths(self) -> None:
        self.client.force_login(self.user)
        ungranted_notebook = Notebook.objects.create(team=self.team, title="Ungranted", short_id="UNGR0001")
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{ungranted_notebook.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class TestGuestDeflectionRuleLoop(APIBaseTest):
    """First matching rule decides the outcome — a matched-but-denied rule must
    deflect rather than letting subsequent rules try the same path."""

    def test_first_matched_rule_decides_even_when_a_later_rule_would_allow(self) -> None:
        from django.http import HttpRequest

        from posthog.middleware_guest import AlwaysAllowed, GuestDeflectionMiddleware, GuestRule

        class AlwaysDenies(GuestRule):
            def allows(self, request, user, match) -> bool:
                return False

        guest = User.objects.create_user(email="ruleloop-guest@example.com", first_name="G", password="p")
        OrganizationMembership.objects.create(organization=self.organization, user=guest, is_guest=True)

        request = HttpRequest()
        request.method = "GET"
        request.path = f"/api/projects/{self.team.pk}/notebooks/foo/"
        request.user = guest

        forwarded = {"called": False}

        def fake_get_response(_req):
            forwarded["called"] = True
            return None

        middleware = GuestDeflectionMiddleware(fake_get_response)
        middleware._rules = [
            AlwaysDenies(r"^/api/projects/\d+/notebooks/.*$"),
            AlwaysAllowed(r"^/api/projects/\d+/notebooks/.*$"),
        ]

        response = middleware(request)
        self.assertFalse(forwarded["called"])
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestGuestDeflectionNotebookGrants(APIBaseTest):
    """Notebook grants address the resource by `short_id` in the URL — Notebook's PK
    is a UUID, not an integer, so the middleware must resolve through `short_id` only.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="notebook-guest@example.com", first_name="N", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        self.granted_notebook = Notebook.objects.create(team=self.team, title="Granted", short_id="GRNT0001")
        self.ungranted_notebook = Notebook.objects.create(team=self.team, title="Hidden", short_id="HIDD0001")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.granted_notebook.short_id,
            created_by=self.user,
            access_level="viewer",
        )

    def test_granted_notebook_short_id_url_is_forwarded(self) -> None:
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.granted_notebook.short_id}/")
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_ungranted_notebook_short_id_url_is_deflected(self) -> None:
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.ungranted_notebook.short_id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_notebook_uuid_in_url_is_deflected(self) -> None:
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.granted_notebook.id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
