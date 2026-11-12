import uuid
import datetime as dt
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project import Project
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal

from products.access_control.backend.models.access_control import AccessControl
from products.aeo.backend.dashboard import (
    DASHBOARD_NAME,
    DASHBOARD_TAG,
    PAGES_SQL,
    SCORECARD_SQL,
    TOPICS_SQL,
    TREND_SQL,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt

TILE_NAMES = ["Non-branded visibility this week", "Visibility trend", "Topics", "Pages to watch"]


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

    def _restrict(self, levels: dict[str, str]) -> None:
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
        ]
        self.organization.save()
        for resource, level in levels.items():
            AccessControl.objects.create(team=self.team, resource=resource, access_level=level)

    @parameterized.expand(
        [
            ("session", True, {}, None, status.HTTP_201_CREATED),
            ("flag_off", False, {}, None, status.HTTP_403_FORBIDDEN),
            ("web_analytics_viewer", True, {"web_analytics": "viewer"}, None, status.HTTP_201_CREATED),
            ("no_web_analytics_access", True, {"web_analytics": "none"}, None, status.HTTP_403_FORBIDDEN),
            ("dashboard_viewer", True, {"dashboard": "viewer"}, None, status.HTTP_403_FORBIDDEN),
            ("insight_viewer", True, {"insight": "viewer"}, None, status.HTTP_403_FORBIDDEN),
            ("key_with_scopes", True, {}, ["web_analytics:read", "dashboard:write", "insight:write"], 201),
            ("key_without_dashboard_write", True, {}, ["web_analytics:write", "insight:write"], 403),
        ]
    )
    def test_create_dashboard(
        self, _name: str, flag_on: bool, levels: dict[str, str], scopes: list[str] | None, expected: int
    ) -> None:
        self.feature_enabled.return_value = flag_on
        self._restrict(levels)
        headers: dict[str, Any] = {}
        if scopes is not None:
            value = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user, label="aeo", secure_value=hash_key_value(value), scopes=scopes
            )
            self.client.logout()
            headers = {"authorization": f"Bearer {value}"}

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
        assert sorted(insight["name"] for insight in insights) == sorted(TILE_NAMES)
        assert all(insight["query"]["kind"] == "DataVisualizationNode" for insight in insights)
        texts = [tile["text"]["body"] for tile in dashboard["tiles"] if tile["text"]]
        assert len(texts) == 1 and "Subscribe" in texts[0]

    def test_dashboard_lands_in_the_requesting_team_only(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

        assert self.client.post(f"/api/projects/{other_team.id}/aeo_prompts/create_dashboard/").status_code == 403
        assert self.client.post(self.url).status_code == status.HTTP_201_CREATED

        assert self.client.get(f"/api/projects/{self.team.id}/dashboards/").json()["count"] == 1


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
        # A citation-sourced domain can carry regex syntax. Its "x|" label must not mark every prompt as branded.
        self._brand(self.team, "x|.example", "own")

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
        # Its stored cited flag points at old.com, which is ignored now, so the citation no longer counts.
        self._check(self.team, 2, "is old any good", "", cited=True, answer="Acme fits", urls=["https://old.com/p"])
        self._check(self.team, 2, "best analytics tool", "analytics", cited=True, failed=True)
        self._check(self.team, 2, "what is Acme", "analytics", cited=True, answer="acme")
        # A no-search answer never cites, so every tile leaves it out rather than count it as uncited.
        self._check(
            self.team, 2, "best analytics tool", "analytics", answer="acme", engine="claude-no-search", mode="no_search"
        )
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
        mode: str = "web_search",
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
                mode=mode,
                cited=cited,
                check_failed=failed,
                answer_text=answer,
                cited_urls=urls or [],
            )
            noon = dt.datetime.combine(self.today - dt.timedelta(days=days_ago), dt.time(12), tzinfo=dt.UTC)
            AEOCitationCheck.objects.filter(pk=check.pk).update(created_at=noon)

    @parameterized.expand(
        [
            ("scorecard", SCORECARD_SQL, [(66.7, 50.0, 16.7, 33.3, 50.0, -16.7, 3, 2)]),
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

    def test_trend_buckets_weeks_ending_yesterday(self) -> None:
        yesterday = self.today - dt.timedelta(days=1)

        assert self._run(TREND_SQL) == [
            (yesterday - dt.timedelta(days=7), 50.0, 50.0, 2),
            (yesterday, 66.7, 33.3, 3),
        ]
