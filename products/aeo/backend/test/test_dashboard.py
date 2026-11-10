import uuid
import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.schema import BreakdownFilter, DataWarehouseNode, DateRange, TrendsFilter, TrendsQuery

from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project import Project
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal

from products.access_control.backend.models.access_control import AccessControl
from products.aeo.backend.dashboard import (
    CITATION_RATE_QUERY,
    DASHBOARD_NAME,
    DASHBOARD_TAG,
    PAGES_SQL,
    TOPICS_SQL,
    TREND_QUERY,
    VISIBILITY_QUERY,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt


class TestCreateDashboardAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "products.aeo.backend.presentation.views.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.feature_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        self.url = f"/api/projects/{self.team.id}/aeo_prompts/create_dashboard/"

    @parameterized.expand(
        [
            ("session", True, True, None, status.HTTP_201_CREATED),
            ("flag_off", False, True, None, status.HTTP_403_FORBIDDEN),
            ("no_dashboard_edit_access", True, False, None, status.HTTP_403_FORBIDDEN),
            ("key_with_scopes", True, True, ["web_analytics:read", "dashboard:write", "insight:write"], 201),
            ("key_without_dashboard_write", True, True, ["web_analytics:write", "insight:write"], 403),
        ]
    )
    def test_create_dashboard(
        self, _name: str, flag_on: bool, can_create: bool, scopes: list[str] | None, expected: int
    ) -> None:
        self.feature_enabled.return_value = flag_on
        headers: dict[str, Any] = {}
        if scopes is not None:
            value = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user, label="aeo", secure_value=hash_key_value(value), scopes=scopes
            )
            self.client.logout()
            headers = {"authorization": f"Bearer {value}"}

        with patch("products.aeo.backend.presentation.views.authorization.check", return_value=can_create):
            response = self.client.post(self.url, headers=headers)

        assert response.status_code == expected, response.json()
        self.client.force_login(self.user)
        dashboards = self.client.get(f"/api/projects/{self.team.id}/dashboards/").json()["results"]
        if expected != status.HTTP_201_CREATED:
            assert dashboards == []
            return
        assert response.json()["name"] == DASHBOARD_NAME
        dashboard = self.client.get(f"/api/projects/{self.team.id}/dashboards/{response.json()['id']}/").json()
        assert (dashboard["name"], dashboard["tags"]) == (DASHBOARD_NAME, [DASHBOARD_TAG])
        insights = [tile["insight"] for tile in dashboard["tiles"] if tile["insight"]]
        assert {insight["name"]: insight["query"]["kind"] for insight in insights} == {
            "Non-branded visibility this week": "InsightVizNode",
            "Non-branded citation rate this week": "InsightVizNode",
            "Visibility trend": "InsightVizNode",
            "Topics": "DataVisualizationNode",
            "Pages to watch": "DataVisualizationNode",
        }
        texts = [tile["text"]["body"] for tile in dashboard["tiles"] if tile["text"]]
        assert len(texts) == 1 and "Subscribe" in texts[0]

    def test_dashboard_lands_in_the_requesting_team_only(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        assert self.client.post(f"/api/projects/{other_team.id}/aeo_prompts/create_dashboard/").status_code == 403
        assert self.client.post(self.url).status_code == status.HTTP_201_CREATED

        assert self.client.get(f"/api/projects/{self.team.id}/dashboards/").json()["count"] == 1

    def test_trends_tiles_load_for_a_member_denied_the_warehouse(self) -> None:
        # A DataWarehouseNode marks the query as a warehouse read, but the checks table is a system table, so
        # people without warehouse access still see the charts.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        for resource in ["warehouse_objects", "warehouse_table", "warehouse_view"]:
            AccessControl.objects.create(team=self.team, resource=resource, access_level="none")

        response = self.client.post(
            f"/api/environments/{self.team.id}/query/", {"query": TREND_QUERY["source"]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [result["label"] for result in response.json()["results"]] == ["Visibility", "Citation rate"]


class TestDashboardQueries(ClickhouseTestMixin, NonAtomicBaseTest):
    # The queries read Postgres through ClickHouse, which only sees committed rows.
    CLASS_DATA_LEVEL_SETUP = False

    def _run(self, query: str) -> list[tuple]:
        return execute_hogql_query(query, team=self.team, user=self.user).results

    def setUp(self) -> None:
        super().setUp()
        # The queries count days from ClickHouse's clock, so the rows are placed at noon on days counted from it.
        self.today: dt.date = self._run("SELECT toDate(now())")[0][0]
        other_org = Organization.objects.create(name="other")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        self._brand(self.team, "acme.com", "own")
        self._brand(self.team, "rival.io", "competitor")
        self._brand(self.team, "old.com", "own", status="ignored")
        self._brand(self.other_team, "beta.com", "own")

        # This week: two analytics answers, one with no topic that mentions the brand in text only,
        # and a failed and a branded check that every tile leaves out.
        self._check(
            self.team,
            2,
            "best analytics tool",
            "analytics",
            cited=True,
            answer="acme is good",
            urls=["https://docs.acme.com/a", "https://rival.io/b"],
        )
        self._check(
            self.team, 2, "best analytics tool", "analytics", answer="rival is good", urls=["https://rival.io/b"]
        )
        self._check(self.team, 2, "is old any good", "", answer="Acme fits", engine="claude-web-search")
        self._check(self.team, 2, "best analytics tool", "analytics", cited=True, failed=True)
        self._check(self.team, 2, "what is Acme", "analytics", cited=True, answer="acme")
        # The week before. "beta" is another team's brand, so the prompt is non-branded here.
        self._check(self.team, 9, "best analytics tool", "analytics", cited=True, urls=["https://docs.acme.com/a"])
        self._check(self.team, 9, "is beta good", "", answer="no")
        self._check(self.other_team, 2, "best analytics tool", "analytics", cited=True, answer="acme")

    def _brand(self, team: Team, domain: str, kind: str, *, status: str = "confirmed") -> None:
        AEOBrand.objects.for_team(team.id).create(
            team=team, name=domain, domain=domain, kind=kind, status=status, source="manual"
        )

    def _check(
        self,
        team: Team,
        days_ago: int,
        prompt_text: str,
        topic: str,
        *,
        cited: bool = False,
        failed: bool = False,
        answer: str = "",
        urls: list[str] | None = None,
        engine: str = "exa-answer",
    ) -> None:
        with team_scope(team.pk):
            prompt, _ = AEOPrompt.objects.get_or_create(
                team=team, prompt_hash=prompt_text, defaults={"prompt": prompt_text, "prompt_source": "manual"}
            )
            check = AEOCitationCheck.objects.create(
                team=team,
                prompt=prompt,
                run_id=uuid.uuid4(),
                prompt_text=prompt_text,
                prompt_source="manual",
                prompt_hash=prompt_text,
                prompt_topic=topic,
                engine=engine,
                model=engine,
                cited=cited,
                check_failed=failed,
                answer_text=answer,
                cited_urls=urls or [],
            )
            noon = dt.datetime.combine(self.today - dt.timedelta(days=days_ago), dt.time(12), tzinfo=dt.UTC)
            AEOCitationCheck.objects.filter(pk=check.pk).update(created_at=noon)

    @parameterized.expand(
        [
            ("topics", TOPICS_SQL, [("No topic", 100.0, 0.0, 100.0, 1), ("analytics", 50.0, 100.0, -50.0, 2)]),
            (
                "pages",
                PAGES_SQL,
                [
                    ("analytics", "Competitor page gained", "https://rival.io/b", 100.0, 0.0, 100.0),
                    ("analytics", "Own page lost", "https://docs.acme.com/a", 50.0, 100.0, -50.0),
                ],
            ),
        ]
    )
    def test_query_numbers(self, _name: str, query: str, expected: list[tuple]) -> None:
        assert self._run(query) == expected

    @parameterized.expand(
        [
            ("visibility", VISIBILITY_QUERY, [("Visibility", "current", 0.667), ("Visibility", "previous", 0.5)]),
            (
                "citation_rate",
                CITATION_RATE_QUERY,
                [("Citation rate", "current", 0.333), ("Citation rate", "previous", 0.5)],
            ),
        ]
    )
    def test_week_over_week_numbers(self, _name: str, query: dict[str, Any], expected: list[tuple]) -> None:
        results = get_query_runner(query["source"], team=self.team).calculate().results

        assert [(r["label"], r["compare_label"], round(r["aggregated_value"], 3)) for r in results] == expected

    def test_trend_has_one_point_per_week(self) -> None:
        results = get_query_runner(TREND_QUERY["source"], team=self.team).calculate().results

        # The two weeks of checks are 7 days apart, so they land in consecutive weeks whatever today's weekday is.
        assert [(r["label"], [round(v, 3) for v in r["data"] if v]) for r in results] == [
            ("Visibility", [0.5, 0.667]),
            ("Citation rate", [0.5, 0.333]),
        ]

    @parameterized.expand(
        [
            ("count", [{}], None, None, [("system.aeo_citation_checks", None, [2, 5])]),
            (
                "breakdown_by_engine",
                [{}],
                "engine",
                None,
                [("exa-answer", "exa-answer", [2, 4]), ("claude-web-search", "claude-web-search", [1])],
            ),
            (
                "formula",
                [{"properties": [{"type": "hogql", "key": "cited"}]}, {}],
                None,
                "A / B",
                [("Formula (A / B)", None, [0.5, 0.6])],
            ),
        ]
    )
    def test_trends_over_the_checks_table(
        self,
        _name: str,
        series: list[dict[str, Any]],
        breakdown: str | None,
        formula: str | None,
        expected: list[tuple],
    ) -> None:
        # The non-zero days of every check of this team, failed and branded included. The other team's check is left out.
        query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id="system.aeo_citation_checks",
                    table_name="system.aeo_citation_checks",
                    timestamp_field="timestamp",
                    id_field="id",
                    distinct_id_field="prompt_id",
                    **overrides,
                )
                for overrides in series
            ],
            dateRange=DateRange(date_from="-14d"),
            breakdownFilter=BreakdownFilter(breakdown=breakdown, breakdown_type="data_warehouse")
            if breakdown
            else None,
            trendsFilter=TrendsFilter(formula=formula),
        )

        results = get_query_runner(query, team=self.team).calculate().results

        assert [(r["label"], r.get("breakdown_value"), [v for v in r["data"] if v]) for r in results] == expected
