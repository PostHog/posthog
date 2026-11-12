import json
import uuid

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework import status

from products.aeo.backend import auto_setup
from products.aeo.backend.facade.api import create_keywords, list_engine_settings
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, BrandStatus, SetupRequest
from products.aeo.backend.models import AEOBrand, AEOKeyword, AEOPrompt
from products.aeo.backend.suggestions import SUGGESTION_CACHE_ALIAS
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
        # Jobs and the per-team running key live in this cache, and the team is shared across the class.
        caches[SUGGESTION_CACHE_ALIAS].clear()

    def _run(
        self,
        responses: list,
        *,
        run_first_check: bool = True,
        first_run_available: bool = True,
        body: dict | None = None,
        enqueue_error: Exception | None = None,
    ) -> tuple[dict, MagicMock, MagicMock]:
        post = MagicMock(side_effect=responses)
        gateway = MagicMock(url="http://gateway", api_key="test-key")
        with (
            patch("products.aeo.backend.suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.keyword_suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.llm.requests.Session.post", post),
            patch("products.aeo.backend.tasks.tasks.citation_tracking_enabled", return_value=first_run_available),
            patch(
                "products.aeo.backend.tasks.tasks.run_aeo_citation_checks_for_team_task.delay",
                side_effect=enqueue_error,
            ) as first_run,
        ):
            started = self.client.post(
                self.url,
                body or {"domain": "https://www.example.com/pricing", "run_first_check": run_first_check},
                format="json",
            )
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
                True,
                "completed",
                [("brand", "done", 1), ("prompts", "done", 3), ("keywords", "done", 1), ("first_run", "done", 0)],
            ),
            (
                "keyword_call_fails_and_setup_goes_on",
                [_answer(PROMPTS_ANSWER), requests.Timeout()],
                True,
                True,
                "completed",
                [("brand", "done", 1), ("prompts", "done", 3), ("keywords", "failed", 0), ("first_run", "done", 0)],
            ),
            (
                "prompt_call_fails_and_setup_stops",
                [requests.Timeout()],
                True,
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
                "configure_only_queues_no_run",
                [_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)],
                False,
                True,
                "completed",
                [("brand", "done", 1), ("prompts", "done", 3), ("keywords", "done", 1), ("first_run", "skipped", 0)],
            ),
            (
                "first_run_not_available",
                [_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)],
                True,
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
        run_first_check: bool,
        first_run_available: bool,
        expected_status: str,
        expected_steps: list[tuple[str, str, int]],
    ) -> None:
        job, _, first_run = self._run(
            responses, run_first_check=run_first_check, first_run_available=first_run_available
        )

        assert job["status"] == expected_status
        assert self._steps(job) == expected_steps
        assert list(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind")) == [
            ("example.com", BrandKind.OWN)
        ]
        prompts_added = expected_steps[1][2]
        assert AEOPrompt.objects.for_team(self.team.id).count() == prompts_added
        assert AEOKeyword.objects.for_team(self.team.id).count() == expected_steps[2][2]
        assert first_run.call_count == (1 if expected_steps[3][1] == "done" else 0)
        if expected_steps[3][1] == "skipped":
            assert job["steps"][3]["detail"] == ("not_available" if run_first_check else "not_requested")

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

    @parameterized.expand(
        [
            ("competitor", BrandKind.COMPETITOR, BrandStatus.CONFIRMED),
            ("ignored_own_brand", BrandKind.OWN, BrandStatus.IGNORED),
            ("ignored_competitor", BrandKind.COMPETITOR, BrandStatus.IGNORED),
        ]
    )
    def test_setup_claims_an_existing_brand_for_the_site(
        self, _name: str, kind: BrandKind, brand_status: BrandStatus
    ) -> None:
        AEOBrand.objects.for_team(self.team.id).create(
            team=self.team,
            name="Example",
            domain="example.com",
            kind=kind,
            status=brand_status,
            source=BrandSource.MANUAL,
        )

        job, _, first_run = self._run([_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)])

        assert self._steps(job)[0] == ("brand", "done", 1)
        assert list(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind", "status")) == [
            ("example.com", BrandKind.OWN, BrandStatus.CONFIRMED)
        ]
        assert first_run.call_count == 1

    def test_run_only_queues_checks_without_consent_or_model_calls(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        create_own_brand(self.team, "example.com")
        AEOPrompt.objects.for_team(self.team.id).create(
            team=self.team, prompt="Question?", prompt_hash="q", prompt_source=AEOPrompt.Source.MANUAL
        )
        create_citation_check(self.team, "earlier")
        engines_before = list_engine_settings(self.team.id)

        job, post, first_run = self._run([], body={"only_first_run": True})

        assert [(s["step"], s["status"], s["detail"]) for s in job["steps"]] == [
            ("brand", "skipped", "not_requested"),
            ("prompts", "skipped", "not_requested"),
            ("keywords", "skipped", "not_requested"),
            ("first_run", "done", ""),
        ]
        assert post.call_count == 0
        assert first_run.call_count == 1
        assert list_engine_settings(self.team.id) == engines_before

    def test_a_failed_enqueue_fails_only_the_first_run_step(self) -> None:
        job, _, _ = self._run(
            [_answer(PROMPTS_ANSWER), _answer(KEYWORDS_ANSWER)], enqueue_error=ConnectionError("broker down")
        )

        assert job["status"] == "completed"
        assert self._steps(job)[3] == ("first_run", "failed", 0)
        assert AEOPrompt.objects.for_team(self.team.id).count() == 3

    def test_a_task_that_starts_too_late_pays_for_nothing(self) -> None:
        job = auto_setup.create_job(self.team.id)
        stored = caches[SUGGESTION_CACHE_ALIAS].get(f"aeo_setup:{self.team.id}:{job.id}")
        stored["started_at"] -= auto_setup.SETUP_START_WINDOW_SECONDS + 1
        caches[SUGGESTION_CACHE_ALIAS].set(f"aeo_setup:{self.team.id}:{job.id}", stored)

        with patch("products.aeo.backend.llm.requests.Session.post") as post:
            auto_setup.run_job(self.team.id, job.id, SetupRequest(domain="example.com"))

        assert post.call_count == 0
        assert auto_setup.load_job(self.team.id, job.id).status == "failed"
        assert AEOBrand.objects.for_team(self.team.id).count() == 0

    def test_a_job_a_reader_marked_failed_stays_failed(self) -> None:
        job = auto_setup.create_job(self.team.id)

        def reader_gives_up(*args: object, **kwargs: object) -> MagicMock:
            auto_setup.fail_job(self.team.id, job.id, auto_setup.STALE_JOB_ERROR)
            return _answer(PROMPTS_ANSWER)

        gateway = MagicMock(url="http://gateway", api_key="test-key")
        with (
            patch("products.aeo.backend.suggestions.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.llm.requests.Session.post", side_effect=reader_gives_up) as post,
        ):
            auto_setup.run_job(self.team.id, job.id, SetupRequest(domain="example.com"))

        assert post.call_count == 1
        assert auto_setup.load_job(self.team.id, job.id).error == auto_setup.STALE_JOB_ERROR

    def test_a_second_setup_while_one_runs_returns_the_running_job(self) -> None:
        with patch("products.aeo.backend.facade.api.set_up_aeo_task.apply_async") as queued:
            first = self.client.post(self.url, {"domain": "example.com"}, format="json")
            second = self.client.post(self.url, {"domain": "example.com"}, format="json")

        assert first.status_code == status.HTTP_202_ACCEPTED
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["job_id"] == first.json()["id"]
        assert queued.call_count == 1

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

    @parameterized.expand(
        [
            ("tracks_only_the_chosen_engines", ["exa-answer"], status.HTTP_202_ACCEPTED, {"exa-answer"}),
            ("unknown_engine", ["exa-answer", "not-an-engine"], status.HTTP_400_BAD_REQUEST, None),
            ("no_chosen_engine_can_run", ["claude-web-search"], status.HTTP_400_BAD_REQUEST, None),
        ]
    )
    @override_settings(EXA_API_KEY="test-key")
    def test_setup_writes_the_chosen_engines_before_the_job(
        self, _name: str, engines: list[str], expected: int, enabled: set[str] | None
    ) -> None:
        before = {s.engine: s.enabled for s in list_engine_settings(self.team.id)}

        with (
            patch("products.aeo.backend.engines.resolve_ai_gateway_config", return_value=None),
            patch("products.aeo.backend.facade.api.set_up_aeo_task.apply_async") as queued,
        ):
            response = self.client.post(self.url, {"domain": "example.com", "engines": engines}, format="json")

        assert response.status_code == expected, response.json()
        assert queued.call_count == (1 if enabled else 0)
        after = list_engine_settings(self.team.id)
        if enabled is None:
            assert {s.engine: s.enabled for s in after} == before
        else:
            assert {s.engine for s in after if s.available and s.enabled} == enabled
            # Engines this deployment cannot run keep their setting, whatever was chosen.
            assert {s.engine: s.enabled for s in after if not s.available} == {
                engine: on for engine, on in before.items() if engine not in {s.engine for s in after if s.available}
            }

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
