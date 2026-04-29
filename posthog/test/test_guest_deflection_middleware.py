from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.rbac.guest_grants import create_grant

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class TestGuestDeflectionMiddleware(APIBaseTest):
    """HTTP-level coverage of the guest deflection rules.

    Setup wires up:
    - one guest user with an optional grant list
    - one granted dashboard + one "tile" insight inheriting access via dashboard cascade
    - one ungranted dashboard / insight / notebook as foils
    """

    def setUp(self) -> None:
        super().setUp()
        # Advanced permissions feature is required for the UserAccessControl layer to honor
        # per-object AC rows. Without it the AC layer short-circuits and guests look no
        # different from members without grants — breaks the cascade tests.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()
        # Promote the base test user to an admin and create a separate guest user.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )

        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        self.granted_dashboard = Dashboard.objects.create(team=self.team, name="Granted dashboard")
        self.ungranted_dashboard = Dashboard.objects.create(team=self.team, name="Ungranted dashboard")
        self.ungranted_insight = Insight.objects.create(team=self.team, name="Ungranted insight")
        self.tile_insight = Insight.objects.create(team=self.team, name="Tile insight")
        DashboardTile.objects.create(dashboard=self.granted_dashboard, insight=self.tile_insight)

    def _login_guest(self) -> None:
        self.client.force_login(self.guest_user)

    def _login_regular(self) -> None:
        self.client.force_login(self.user)

    def _grant(self, resource: str, resource_id: str) -> None:
        # Write via the service so the AC rows + dashboard-tile cascade match what the invite
        # flow would produce. The middleware reads AC rows now that `is_guest=True` inverts
        # the AC default.
        target_pk: int
        if resource == "dashboard":
            target_pk = Dashboard.objects.get(pk=int(resource_id)).pk
        elif resource == "insight":
            target_pk = (
                Insight.objects.get(pk=int(resource_id)).pk
                if resource_id.isdigit()
                else Insight.objects.get(short_id=resource_id).pk
            )
        else:
            raise AssertionError(f"Unsupported resource in test helper: {resource}")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource=resource,
            resource_id=str(target_pk),
            created_by=self.user,
        )

    def test_non_guest_user_is_never_deflected(self) -> None:
        self._login_regular()
        res = self.client.get(f"/api/projects/{self.team.pk}/dashboards/{self.ungranted_dashboard.pk}/")
        # Regular admin can read any dashboard they have AC on; the middleware doesn't deflect them.
        self.assertNotEqual(res.status_code, 404)

    def test_guest_user_without_grants_is_deflected_from_api(self) -> None:
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/dashboards/{self.ungranted_dashboard.pk}/")
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
        # Route exists in frontend only, but middleware must not redirect; Django should reach
        # the SPA/catch-all handler. We only care that the status is not a 302 to /guest.
        self.assertNotEqual(res.status_code, status.HTTP_302_FOUND)

    def test_guest_with_dashboard_grant_can_read_granted_dashboard(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/dashboards/{self.granted_dashboard.pk}/")
        self.assertNotEqual(res.status_code, 404)

    def test_guest_with_dashboard_grant_cannot_read_other_dashboard(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/dashboards/{self.ungranted_dashboard.pk}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_query_with_matching_scene_header_is_allowed(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            data={"query": {"kind": "HogQLQuery", "query": "SELECT 1"}},
            content_type="application/json",
            HTTP_X_POSTHOG_SCENE_RESOURCE=f"dashboard:{self.granted_dashboard.pk}",
        )
        self.assertNotEqual(res.status_code, 404)

    def test_query_with_mismatched_scene_header_is_deflected(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            data={"query": {"kind": "HogQLQuery", "query": "SELECT 1"}},
            content_type="application/json",
            HTTP_X_POSTHOG_SCENE_RESOURCE=f"dashboard:{self.ungranted_dashboard.pk}",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_query_without_scene_header_is_deflected(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            data={"query": {"kind": "HogQLQuery", "query": "SELECT 1"}},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_query_with_malformed_scene_header_is_deflected(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            data={"query": {"kind": "HogQLQuery", "query": "SELECT 1"}},
            content_type="application/json",
            HTTP_X_POSTHOG_SCENE_RESOURCE="garbage-no-colon",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_themes_metadata_is_allowed_for_guest_with_any_grant(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.get(f"/api/projects/{self.team.pk}/data_color_themes/")
        self.assertNotEqual(res.status_code, 404)

    def test_themes_metadata_post_is_deflected(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.post(
            f"/api/projects/{self.team.pk}/data_color_themes/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_tile_insight_is_allowed_when_parent_dashboard_is_granted(self) -> None:
        # Dashboard grant cascades AC rows to tile insights; the middleware's list filter
        # resolves the insight by short_id and the AC row lets it through.
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.get(
            f"/api/projects/{self.team.pk}/insights/",
            {"short_id": self.tile_insight.short_id},
        )
        self.assertNotEqual(res.status_code, 404)

    def test_non_tile_insight_is_deflected_with_only_dashboard_grant(self) -> None:
        self._grant("dashboard", str(self.granted_dashboard.pk))
        self._login_guest()
        res = self.client.get(
            f"/api/projects/{self.team.pk}/insights/",
            {"short_id": self.ungranted_insight.short_id},
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
            # Each endpoint is only registered on one of the routers (projects vs environments).
            # We pair the endpoint with the scope where Django actually has a URL pattern —
            # otherwise a regular Django 404 is indistinguishable from a middleware 404.
            ("annotations", "projects"),
            ("cohorts", "projects"),
            ("tags", "projects"),
            ("insight_variables", "environments"),
            ("quick_filters", "environments"),
            ("data_color_themes", "environments"),
        ]
    )
    def test_metadata_endpoints_require_any_grant(self, endpoint: str, scope: str) -> None:
        # No grants yet — middleware should deflect even though the endpoint is in the
        # metadata allowlist (guests with zero grants have no business in team metadata).
        self._login_guest()
        url = f"/api/{scope}/{self.team.pk}/{endpoint}/"
        res_without_grant = self.client.get(url)
        self.assertEqual(res_without_grant.status_code, status.HTTP_404_NOT_FOUND)

        self._grant("dashboard", str(self.granted_dashboard.pk))
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
        # Original `self.organization` is org A — promote `self.user` to a guest there.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(is_guest=True)
        # Org B with a separate team where the same user is a regular member.
        from posthog.models import Organization, Team

        self.org_b = Organization.objects.create(name="Org B")
        OrganizationMembership.objects.create(
            organization=self.org_b,
            user=self.user,
            is_guest=False,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.team_b = Team.objects.create_with_data(organization=self.org_b, name="Team B", initiating_user=self.user)
        self.dashboard_b = Dashboard.objects.create(team=self.team_b, name="Org B dashboard")

    def test_guest_in_other_org_is_not_deflected_on_target_org_paths(self) -> None:
        # User is a guest in org A but a regular admin in org B. Hitting an org-B path
        # must not invoke guest deflection — they're a normal member there.
        self.client.force_login(self.user)
        res = self.client.get(f"/api/projects/{self.team_b.pk}/dashboards/{self.dashboard_b.pk}/")
        # Either 200 (admin can read) or any non-404 — the key invariant is "not deflected."
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_guest_in_same_org_is_deflected_on_ungranted_paths(self) -> None:
        # On their guest-org's paths the user IS a guest and gets deflected for
        # ungranted resources — the cross-org carve-out doesn't widen anything.
        self.client.force_login(self.user)
        ungranted_dashboard = Dashboard.objects.create(team=self.team, name="Ungranted")
        res = self.client.get(f"/api/projects/{self.team.pk}/dashboards/{ungranted_dashboard.pk}/")
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

        # Build a request that the rule pair both match.
        request = HttpRequest()
        request.method = "GET"
        request.path = f"/api/projects/{self.team.pk}/dashboards/1/"
        request.user = guest

        # Spy on the wrapped get_response to confirm the deny rule short-circuits.
        forwarded = {"called": False}

        def fake_get_response(_req):
            forwarded["called"] = True
            return None

        middleware = GuestDeflectionMiddleware(fake_get_response)
        middleware._rules = [
            AlwaysDenies(r"^/api/projects/\d+/dashboards/.*$"),
            AlwaysAllowed(r"^/api/projects/\d+/dashboards/.*$"),
        ]

        response = middleware(request)
        self.assertFalse(forwarded["called"])  # never reached the inner view
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

        from products.notebooks.backend.models import Notebook

        self.granted_notebook = Notebook.objects.create(team=self.team, title="Granted", short_id="GRNT0001")
        self.ungranted_notebook = Notebook.objects.create(team=self.team, title="Hidden", short_id="HIDD0001")
        # Grant via the service so the AC row matches the production flow (UUID PK stored).
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
        # Notebook URLs are addressed by short_id; a guest who has the granted notebook's UUID
        # cannot use it as the URL identifier — middleware looks up by short_id only.
        self.client.force_login(self.guest_user)
        res = self.client.get(f"/api/projects/{self.team.pk}/notebooks/{self.granted_notebook.id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class TestGuestDeflectionTeamScopedPostSubActions(APIBaseTest):
    """`/insights/cancel/`, `/insights/timing/`, `/insights/viewed/` are POST sub-actions
    a viewer client fires automatically while interacting with a dashboard tile (cancel a
    running query, record query timing, mark insight as viewed). The middleware must allow
    them when the guest has any AC row in the team — without this, changing the date picker
    on a granted dashboard fails because the FE-issued cancel hits 404, leaving the previous
    query running and the new one stalled.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

        self.guest_user_with_grant = User.objects.create_user(
            email="grant-guest@example.com", first_name="G", password="password123"
        )
        self.guest_membership_with_grant = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user_with_grant, is_guest=True
        )
        # Grant a dashboard with at least one tile, so the cascade writes a viewer-level
        # insight AC row. This mirrors production: the FE only fires `cancel`/`timing` while
        # tile queries are running, so the realistic permission check has the cascade row to
        # satisfy `has_any_specific_access("insight", "viewer")`.
        from posthog.models.insight import Insight

        from products.dashboards.backend.models.dashboard_tile import DashboardTile

        self.granted_dashboard = Dashboard.objects.create(team=self.team, name="Granted")
        tile_insight = Insight.objects.create(team=self.team, name="Tile")
        DashboardTile.objects.create(dashboard=self.granted_dashboard, insight=tile_insight)
        create_grant(
            membership=self.guest_membership_with_grant,
            team=self.team,
            resource="dashboard",
            resource_id=str(self.granted_dashboard.pk),
            created_by=self.user,
            access_level="viewer",
        )

        self.guest_user_no_grant = User.objects.create_user(
            email="nogrant-guest@example.com", first_name="N", password="password123"
        )
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user_no_grant, is_guest=True
        )

    @parameterized.expand([("cancel",), ("timing",), ("viewed",)])
    def test_post_subaction_forwarded_for_guest_with_grant(self, subaction: str) -> None:
        self.client.force_login(self.guest_user_with_grant)
        res = self.client.post(
            f"/api/projects/{self.team.pk}/insights/{subaction}/",
            data={"client_query_id": "test-query-id"},
            content_type="application/json",
        )
        # Viewset may 400 on missing payload fields, but the request must REACH the viewset
        # (i.e. middleware must not 404 it AND the AC permission layer must not 403 it).
        # `cancel` and `timing` declare `required_scopes=["insight:read"]` so guests with any
        # specific insight access (including the dashboard-tile cascade) pass the resource
        # check; `viewed` already declared the same scope before this PR.
        self.assertNotEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_returns_201_for_guest_with_tile_cascade(self) -> None:
        # End-to-end success check: cancel takes a `client_query_id` and signals ClickHouse
        # to abort. With the tile cascade row in place, the guest passes both the middleware
        # gate AND the AC `has_any_specific_access("insight", "viewer")` check. 201 confirms
        # the action ran (it doesn't matter that no query is actually running — cancel is
        # idempotent).
        self.client.force_login(self.guest_user_with_grant)
        res = self.client.post(
            f"/api/projects/{self.team.pk}/insights/cancel/",
            data={"client_query_id": "test-query-id"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    @parameterized.expand([("cancel",), ("timing",), ("viewed",)])
    def test_post_subaction_deflected_for_guest_without_any_team_ac_row(self, subaction: str) -> None:
        # A guest with zero AC rows in this team has no business hitting team-scoped POST
        # endpoints. Same gate as the metadata-read rule.
        self.client.force_login(self.guest_user_no_grant)
        res = self.client.post(
            f"/api/projects/{self.team.pk}/insights/{subaction}/",
            data={"client_query_id": "test-query-id"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_on_post_subaction_path_is_deflected(self) -> None:
        # The rule is POST-only — a GET on the same path falls through to the next rule
        # (GrantBoundResource("insight")), which tries to look up an insight with short_id
        # equal to the action name and fails.
        self.client.force_login(self.guest_user_with_grant)
        res = self.client.get(f"/api/projects/{self.team.pk}/insights/cancel/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
