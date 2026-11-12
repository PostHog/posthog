import json
import uuid

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from rest_framework import status

from products.aeo.backend.facade.api import create_keywords
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, BrandStatus
from products.aeo.backend.models import AEOBrand, AEOKeyword, AEOPrompt
from products.aeo.backend.test.factories import create_citation_check, create_own_brand

PROMPTS_ANSWER = [
    {"prompt": f"Best session replay tool {i}?", "topic": "Replay", "circle": "battleground", "funnel_stage": "top"}
    for i in range(3)
]
KEYWORDS_ANSWER = [{"keyword": "session replay", "reason": "Buyers search for it."}]


def _answer(items: list[dict]) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(items)}]}
    return response


class TestAEOSetupAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch("products.aeo.backend.presentation.views.posthog_feature_flag_enabled", return_value=True)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/aeo_setup/"

    def _run(self, responses: list, *, first_run_available: bool = True) -> tuple[dict, MagicMock, MagicMock]:
        post = MagicMock(side_effect=responses)
        gateway = MagicMock(url="http://gateway", api_key="test-key")
        with (
            patch("products.aeo.backend.suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.keyword_suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.llm.requests.Session.post", post),
            patch("products.aeo.backend.tasks.tasks.citation_tracking_enabled", return_value=first_run_available),
            patch("products.aeo.backend.tasks.tasks.run_aeo_citation_checks_for_team_task.delay") as first_run,
        ):
            started = self.client.post(self.url, {"domain": "https://www.example.com/pricing"}, format="json")
        assert started.status_code == status.HTTP_202_ACCEPTED, started.json()
        job = self.client.get(f"{self.url}{started.json()['id']}/").json()
        return job, post, first_run

    @staticmethod
    def _steps(job: dict) -> list[tuple[str, str, int]]:
        return [(s["step"], s["status"], s["added"]) for s in job["steps"]]

    @parameterized.expand(
        [
            (
                "everything_runs",
                [_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)],
                True,
                "completed",
                [("brand", "done", 1), ("prompts", "done", 3), ("keywords", "done", 1), ("first_run", "done", 0)],
            ),
            (
                "keyword_call_fails_and_setup_goes_on",
                [_answer(PROMPTS_ANSWER), requests.Timeout()],
                True,
                "completed",
                [("brand", "done", 1), ("prompts", "done", 3), ("keywords", "failed", 0), ("first_run", "done", 0)],
            ),
            (
                "prompt_call_fails_and_setup_stops",
                [requests.Timeout()],
                True,
                "failed",
                [
                    ("brand", "done", 1),
                    ("prompts", "failed", 0),
                    ("keywords", "pending", 0),
                    ("first_run", "pending", 0),
                ],
            ),
            (
                "first_run_not_available",
                [_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)],
                False,
                "completed",
                [("brand", "done", 1), ("prompts", "done", 3), ("keywords", "done", 1), ("first_run", "skipped", 0)],
            ),
        ]
    )
    def test_setup_saves_each_step_for_a_new_project(
        self,
        _name: str,
        responses: list,
        first_run_available: bool,
        expected_status: str,
        expected_steps: list[tuple[str, str, int]],
    ) -> None:
        job, _, first_run = self._run(responses, first_run_available=first_run_available)

        assert job["status"] == expected_status
        assert self._steps(job) == expected_steps
        assert list(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind")) == [
            ("example.com", BrandKind.OWN)
        ]
        prompts_added = expected_steps[1][2]
        assert AEOPrompt.objects.for_team(self.team.id).count() == prompts_added
        assert AEOKeyword.objects.for_team(self.team.id).count() == expected_steps[2][2]
        assert first_run.call_count == (1 if expected_steps[3][1] == "done" else 0)

    def test_setup_skips_every_step_a_project_already_covers(self) -> None:
        create_own_brand(self.team, "example.com")
        for i in range(10):
            AEOPrompt.objects.for_team(self.team.id).create(
                team=self.team, prompt=f"Question {i}?", prompt_hash=f"q{i}", prompt_source=AEOPrompt.Source.MANUAL
            )
        create_keywords(self.team.id, [f"keyword {i}" for i in range(10)])
        create_citation_check(self.team, "existing")

        job, post, first_run = self._run([])

        assert job["status"] == "completed"
        assert [(s["step"], s["status"]) for s in job["steps"]] == [
            ("brand", "skipped"),
            ("prompts", "skipped"),
            ("keywords", "skipped"),
            ("first_run", "skipped"),
        ]
        assert post.call_count == 0
        assert first_run.call_count == 0

    def test_setup_claims_a_competitor_brand_for_the_site(self) -> None:
        AEOBrand.objects.for_team(self.team.id).create(
            team=self.team,
            name="Example",
            domain="example.com",
            kind=BrandKind.COMPETITOR,
            status=BrandStatus.CONFIRMED,
            source=BrandSource.MANUAL,
        )

        job, _, _ = self._run([_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)])

        assert self._steps(job)[0] == ("brand", "done", 1)
        assert list(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind")) == [
            ("example.com", BrandKind.OWN)
        ]

    @parameterized.expand(
        [
            ("no_ai_consent", False, "example.com", status.HTTP_403_FORBIDDEN),
            ("not_a_domain", True, "localhost", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_setup_refuses_to_start(self, _name: str, ai_approved: bool, domain: str, expected: int) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        with patch("products.aeo.backend.facade.api.set_up_aeo_task.apply_async") as queued:
            response = self.client.post(self.url, {"domain": domain}, format="json")

        assert response.status_code == expected
        assert queued.call_count == 0
        assert AEOBrand.objects.for_team(self.team.id).count() == 0

    def test_get_returns_404_for_an_unknown_job(self) -> None:
        assert self.client.get(f"{self.url}{uuid.uuid4()}/").status_code == status.HTTP_404_NOT_FOUND

    def test_context_lists_websites_from_every_source_in_order(self) -> None:
        create_own_brand(self.team, "brand.com")
        self.team.app_urls = ["https://app.brand.com", "https://www.authorized.com/path"]
        self.team.recording_domains = ["https://recorded.io"]
        self.team.save(update_fields=["app_urls", "recording_domains"])
        for host, count in [("docs.visited.dev", 2), ("www.visited.dev", 1), ("localhost", 5), ("busy.org", 1)]:
            for _ in range(count):
                _create_event(team=self.team, event="$pageview", distinct_id="user", properties={"$host": host})
        flush_persons_and_events()

        context = self.client.get(f"{self.url}context/").json()

        assert [(w["domain"], w["source"], w["pageviews"]) for w in context["websites"]] == [
            ("brand.com", "own_brand", None),
            ("authorized.com", "app_urls", None),
            ("recorded.io", "recording_domains", None),
            ("visited.dev", "pageviews", 3),
            ("busy.org", "pageviews", 1),
        ]
        assert context["own_domains"] == ["brand.com"]
        assert context["ai_data_processing_approved"] is True
