from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from rest_framework.exceptions import NotFound

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.rbac._generated_guest_overridable import GUEST_OVERRIDABLE_FIELDS
from posthog.rbac.guest_grants import create_grant
from posthog.rbac.guest_query_scope import rescope_guest_query

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


def _request(user, data: dict, headers: dict | None = None):
    req = MagicMock()
    req.user = user
    req.data = data
    req.headers = headers or {}
    return req


class TestGuestOverridableGeneratedMap(BaseTest):
    """Structural checks on the codegen'd whitelist — catches accidental
    annotation regressions at PR-review time without having to read the
    `_generated_guest_overridable.py` file."""

    @parameterized.expand(
        [
            ("TrendsQuery", "trendsFilter"),
            ("TrendsQuery", "breakdownFilter"),
            ("TrendsQuery", "compareFilter"),
            ("TrendsQuery", "dateRange"),
            ("TrendsQuery", "properties"),
            ("TrendsQuery", "filterTestAccounts"),
            ("TrendsQuery", "samplingFactor"),
            ("FunnelsQuery", "funnelsFilter"),
            ("FunnelsQuery", "breakdownFilter"),
            ("RetentionQuery", "retentionFilter"),
            ("PathsQuery", "pathsFilter"),
            ("StickinessQuery", "stickinessFilter"),
            ("LifecycleQuery", "lifecycleFilter"),
            ("CalendarHeatmapQuery", "dateRange"),
        ]
    )
    def test_expected_fields_are_overridable(self, kind: str, field: str) -> None:
        self.assertIn(kind, GUEST_OVERRIDABLE_FIELDS, f"{kind} missing from generated whitelist")
        self.assertIn(field, GUEST_OVERRIDABLE_FIELDS[kind], f"{kind}.{field} should be overridable")

    @parameterized.expand(
        [
            ("TrendsQuery", "series"),
            ("TrendsQuery", "kind"),
            ("FunnelsQuery", "series"),
            ("RetentionQuery", "kind"),
        ]
    )
    def test_structural_fields_are_not_overridable(self, kind: str, field: str) -> None:
        self.assertNotIn(
            field,
            GUEST_OVERRIDABLE_FIELDS.get(kind, frozenset()),
            f"{kind}.{field} must not be overridable — it defines the query's shape",
        )

    def test_hogql_query_has_no_overridable_fields(self) -> None:
        # HogQLQuery has no guest-overridable fields — guests should never be
        # able to send arbitrary HogQL.
        self.assertNotIn("HogQLQuery", GUEST_OVERRIDABLE_FIELDS)

    def test_events_query_has_no_overridable_fields(self) -> None:
        self.assertNotIn("EventsQuery", GUEST_OVERRIDABLE_FIELDS)

    def test_actors_query_has_no_overridable_fields(self) -> None:
        self.assertNotIn("ActorsQuery", GUEST_OVERRIDABLE_FIELDS)


class TestRescopeGuestQuery(BaseTest):
    """End-to-end behavior of the rescoper when mutating request.data."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        # Saved TrendsQuery that the guest has been granted access to.
        self.saved_trends_query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "dau"}],
            "trendsFilter": {"display": "ActionsLineGraph"},
            "dateRange": {"date_from": "-30d"},
        }
        self.insight = Insight.objects.create(
            team=self.team,
            short_id="AAAAAAAA",
            name="DAUs",
            query=self.saved_trends_query,
        )
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="insight",
            resource_id=self.insight.short_id,
            created_by=self.user,
            access_level="viewer",
        )

    def test_matching_kind_discards_malicious_series(self) -> None:
        # Guest submits a TrendsQuery body with a DIFFERENT series than the
        # saved insight. Series is not whitelisted; must be discarded.
        body = {
            "query": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$signup"}],  # DIFFERENT
                "trendsFilter": {"display": "ActionsBar"},  # overridable
            }
        }
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": f"insight:{self.insight.short_id}"},
        )
        rescope_guest_query(req, team_id=self.team.id)

        # Series comes from the saved query (not the client's malicious override).
        self.assertEqual(
            req.data["query"]["series"],
            self.saved_trends_query["series"],
        )
        # trendsFilter is overridable — the client's value wins.
        self.assertEqual(req.data["query"]["trendsFilter"], {"display": "ActionsBar"})
        # dateRange wasn't in the client body — falls back to the saved query.
        self.assertEqual(req.data["query"]["dateRange"], {"date_from": "-30d"})

    def test_kind_mismatch_raises_404(self) -> None:
        # Guest submits an EventsQuery body but header names a TrendsQuery insight.
        body = {"query": {"kind": "EventsQuery", "select": ["*"]}}
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": f"insight:{self.insight.short_id}"},
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)

    def test_hogql_query_in_body_with_trends_grant_is_rejected(self) -> None:
        body = {"query": {"kind": "HogQLQuery", "query": "SELECT * FROM events"}}
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": f"insight:{self.insight.short_id}"},
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)

    def test_missing_header_raises_404(self) -> None:
        body = {"query": {"kind": "TrendsQuery", "series": []}}
        req = _request(self.guest_user, body, headers={})
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)

    def test_malformed_header_raises_404(self) -> None:
        body = {"query": {"kind": "TrendsQuery", "series": []}}
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": "evil"},
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)

    def test_non_granted_insight_raises_404(self) -> None:
        body = {"query": {"kind": "TrendsQuery", "series": []}}
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": "insight:NOTGRANT"},
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)

    def test_date_range_override_applies(self) -> None:
        body = {
            "query": {
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-7d"},
            }
        }
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": f"insight:{self.insight.short_id}"},
        )
        rescope_guest_query(req, team_id=self.team.id)
        self.assertEqual(req.data["query"]["dateRange"], {"date_from": "-7d"})
        # series still comes from the saved query
        self.assertEqual(req.data["query"]["series"], self.saved_trends_query["series"])

    def test_unwraps_insight_viz_node(self) -> None:
        # Some saved insights store InsightVizNode { source: TrendsQuery{...} }.
        # The /query/ endpoint runs the inner source node.
        self.insight.query = {
            "kind": "InsightVizNode",
            "source": self.saved_trends_query,
        }
        self.insight.save()
        body = {"query": {"kind": "TrendsQuery", "dateRange": {"date_from": "-7d"}}}
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": f"insight:{self.insight.short_id}"},
        )
        rescope_guest_query(req, team_id=self.team.id)
        self.assertEqual(req.data["query"]["kind"], "TrendsQuery")
        self.assertEqual(req.data["query"]["series"], self.saved_trends_query["series"])


class TestRescopeGuestQueryDashboardGrant(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        self.dashboard = Dashboard.objects.create(team=self.team, name="D")
        self.tile_insight = Insight.objects.create(
            team=self.team,
            short_id="TILEINS1",
            name="Tile",
            query={
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
            },
        )
        DashboardTile.objects.create(dashboard=self.dashboard, insight=self.tile_insight)
        # create_grant cascades an AC row to each tile insight, so the guest can
        # address a tile via the dashboard scene resource.
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=str(self.dashboard.pk),
            created_by=self.user,
            access_level="viewer",
        )

    def test_dashboard_grant_requires_tile_insight_short_id_header(self) -> None:
        body = {"query": {"kind": "TrendsQuery"}}
        # No tile short_id → 404
        req = _request(
            self.guest_user,
            body,
            {"X-PostHog-Scene-Resource": f"dashboard:{self.dashboard.pk}"},
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)

    def test_dashboard_grant_with_tile_short_id_succeeds(self) -> None:
        body = {
            "query": {
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-7d"},
            }
        }
        req = _request(
            self.guest_user,
            body,
            {
                "X-PostHog-Scene-Resource": f"dashboard:{self.dashboard.pk}",
                "X-PostHog-Scene-Tile-Insight-Short-Id": self.tile_insight.short_id,
            },
        )
        rescope_guest_query(req, team_id=self.team.id)
        self.assertEqual(req.data["query"]["dateRange"], {"date_from": "-7d"})
        # series comes from the saved tile insight
        self.assertEqual(
            req.data["query"]["series"],
            [{"kind": "EventsNode", "event": "$pageview"}],
        )

    def test_dashboard_grant_rejects_non_tile_insight(self) -> None:
        # Another insight in the same team that is NOT a tile of the granted dashboard.
        other_insight = Insight.objects.create(
            team=self.team,
            short_id="OTHER001",
            name="Other",
            query={"kind": "TrendsQuery", "series": []},
        )
        req = _request(
            self.guest_user,
            {"query": {"kind": "TrendsQuery"}},
            {
                "X-PostHog-Scene-Resource": f"dashboard:{self.dashboard.pk}",
                "X-PostHog-Scene-Tile-Insight-Short-Id": other_insight.short_id,
            },
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.team.id)


# Guest detection moved to `posthog.rbac.guest_request_cache` (request-scoped cache so
# the middleware and downstream consumers share one DB lookup). See
# `posthog/rbac/test/test_guest_request_cache.py` for coverage of that helper.


class TestRescopeGuestQueryTeamScoping(BaseTest):
    """A grant in team A must not satisfy a query targeting team B, even when
    insights in different teams happen to share a short_id."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="guest-cross@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

        # Two teams. Same short_id used in both — the guest is granted only the team-A copy.
        from posthog.models.team import Team

        self.other_team = Team.objects.create_with_data(
            organization=self.organization, name="Team B", initiating_user=self.user
        )
        shared_short_id = "SHAREDID"
        self.granted_insight = Insight.objects.create(
            team=self.team,
            short_id=shared_short_id,
            name="Granted",
            query={
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview"}],
                "dateRange": {"date_from": "-30d"},
            },
        )
        Insight.objects.create(
            team=self.other_team,
            short_id=shared_short_id,
            name="Untouchable team-B insight",
            query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$signup"}]},
        )
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="insight",
            resource_id=self.granted_insight.short_id,
            created_by=self.user,
            access_level="viewer",
        )

    def test_rescoper_rejects_grant_when_request_targets_different_team(self) -> None:
        # Header points at the same short_id but the request targets team B (which has
        # an insight with the same short_id but no grant). Must 404 — the team-A grant
        # cannot satisfy a team-B query.
        req = _request(
            self.guest_user,
            {"query": {"kind": "TrendsQuery"}},
            {"X-PostHog-Scene-Resource": f"insight:{self.granted_insight.short_id}"},
        )
        with self.assertRaises(NotFound):
            rescope_guest_query(req, team_id=self.other_team.id)

    def test_rescoper_accepts_grant_when_request_targets_same_team(self) -> None:
        req = _request(
            self.guest_user,
            {"query": {"kind": "TrendsQuery"}},
            {"X-PostHog-Scene-Resource": f"insight:{self.granted_insight.short_id}"},
        )
        rescope_guest_query(req, team_id=self.team.id)
        self.assertEqual(req.data["query"]["kind"], "TrendsQuery")
