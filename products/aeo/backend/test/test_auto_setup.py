import json
import time
import uuid
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status

from products.aeo.backend import auto_setup, catalog, credits, prompt_limit, run_stop
from products.aeo.backend.engine_settings import engine_schedule
from products.aeo.backend.facade.api import create_keywords, list_engine_settings
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, BrandStatus, SetupRequest
from products.aeo.backend.models import AEOBrand, AEOKeyword, AEOPrompt, AEOPromptVersion
from products.aeo.backend.seeding import prompt_hash
from products.aeo.backend.suggestions import SUGGESTION_CACHE_ALIAS
from products.aeo.backend.test.factories import ai_credits_used_up, create_citation_check, create_own_brand

PROMPTS_ANSWER = [
    {"prompt": f"Best session replay tool {i}?", "topic": "Replay", "circle": "battleground", "funnel_stage": "top"}
    for i in range(3)
]
KEYWORDS_ANSWER = [{"keyword": "session replay", "reason": "Buyers search for it."}]


def _answer(items: list[dict] | dict) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(items)}]}
    return response


def _prompt_answers(answer: list[dict] | dict = PROMPTS_ANSWER) -> list[MagicMock]:
    research = {
        "brand": "Example",
        "category": "session replay",
        "description": "Session replay for web apps.",
        "competitors": answer.get("competitors", []) if isinstance(answer, dict) else [],
    }
    return [_answer(research), _answer(answer), _answer([])]


class _LazyFuture:
    def __init__(self, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        self._call = lambda: fn(*args, **kwargs)

    def result(self) -> Any:
        return self._call()


class _LazyExecutor:
    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> _LazyFuture:
        return _LazyFuture(fn, args, kwargs)

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        pass


class TestAEOSetupAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Keyword picking runs beside prompt writing; here it runs when setup collects it, so the canned answers
        # are consumed in the order the tests list them. The parallel test below uses real threads.
        pool_patcher = patch("products.aeo.backend.auto_setup._keyword_pool", return_value=_LazyExecutor())
        pool_patcher.start()
        self.addCleanup(pool_patcher.stop)
        retry_patcher = patch("products.aeo.backend.suggestions.TRANSIENT_RETRY_SECONDS", 0)
        retry_patcher.start()
        self.addCleanup(retry_patcher.stop)
        flag_patcher = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/aeo_setup/"
        # Jobs and the per-team running key live in this cache, and the team is shared across the class.
        caches[SUGGESTION_CACHE_ALIAS].clear()

    def _run(
        self,
        responses: list | Callable[..., Any],
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
            # Without a gateway no engine is available, and the first run would find nothing to run.
            patch("products.aeo.backend.engines.resolve_ai_gateway_config", return_value=gateway),
            patch("products.aeo.backend.llm.requests.Session.post", post),
            patch("products.aeo.backend.tasks.tasks.citation_tracking_enabled", return_value=first_run_available),
            patch(
                "products.aeo.backend.tasks.tasks.run_aeo_citation_checks_for_team_task.delay",
                side_effect=enqueue_error,
            ) as first_run,
        ):
            self.calls = MagicMock()
            self.calls.attach_mock(post, "model")
            self.calls.attach_mock(first_run, "first_run")
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

    def test_setup_asks_for_the_prompt_count_the_person_chose(self) -> None:
        job, post, _ = self._run(
            [*_prompt_answers(), _answer(KEYWORDS_ANSWER)],
            body={"domain": "example.com", "run_first_check": False, "prompt_count": 3},
        )

        assert job["status"] == "completed"
        instructions = post.call_args_list[1].kwargs["json"]["messages"][0]["content"]
        assert "write 3 prompts" in instructions
        assert (job["steps"][2]["added"], job["steps"][2]["requested"], job["steps"][2]["detail"]) == (3, 3, "paused")

    @parameterized.expand(
        [
            (
                "everything_runs",
                [*_prompt_answers(), _answer(KEYWORDS_ANSWER)],
                True,
                True,
                "completed",
                [
                    ("brand", "done", 1),
                    ("research", "done", 0),
                    ("prompts", "done", 3),
                    ("first_run", "done", 0),
                    ("keywords", "done", 1),
                ],
            ),
            (
                "keyword_call_fails_and_setup_goes_on",
                [*_prompt_answers(), requests.Timeout()],
                True,
                True,
                "completed",
                [
                    ("brand", "done", 1),
                    ("research", "done", 0),
                    ("prompts", "done", 3),
                    ("first_run", "done", 0),
                    ("keywords", "failed", 0),
                ],
            ),
            (
                "site_research_fails_and_setup_stops",
                [requests.Timeout(), requests.Timeout()],
                True,
                True,
                "failed",
                [
                    ("brand", "done", 1),
                    ("research", "failed", 0),
                    ("prompts", "pending", 0),
                    ("first_run", "pending", 0),
                    ("keywords", "pending", 0),
                ],
            ),
            (
                "prompt_call_fails_and_setup_stops",
                [_prompt_answers()[0], requests.Timeout(), requests.Timeout()],
                True,
                True,
                "failed",
                [
                    ("brand", "done", 1),
                    ("research", "done", 0),
                    ("prompts", "failed", 0),
                    ("first_run", "pending", 0),
                    ("keywords", "skipped", 0),
                ],
            ),
            (
                "configure_only_queues_no_run",
                [*_prompt_answers(), _answer(KEYWORDS_ANSWER)],
                False,
                True,
                "completed",
                [
                    ("brand", "done", 1),
                    ("research", "done", 0),
                    ("prompts", "done", 3),
                    ("first_run", "skipped", 0),
                    ("keywords", "done", 1),
                ],
            ),
            (
                "first_run_not_available",
                [*_prompt_answers(), _answer(KEYWORDS_ANSWER)],
                True,
                False,
                "completed",
                [
                    ("brand", "done", 1),
                    ("research", "done", 0),
                    ("prompts", "done", 3),
                    ("first_run", "skipped", 0),
                    ("keywords", "done", 1),
                ],
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
        job, post, first_run = self._run(
            responses, run_first_check=run_first_check, first_run_available=first_run_available
        )

        assert job["status"] == expected_status
        assert [call.kwargs["headers"]["X-PostHog-Product"] for call in post.call_args_list] == ["ai_visibility"] * len(
            responses
        )
        assert self._steps(job) == expected_steps
        assert list(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind")) == [
            ("example.com", BrandKind.OWN)
        ]
        prompts_added = next(added for step, _, added in expected_steps if step == "prompts")
        assert AEOPrompt.objects.for_team(self.team.id).count() == prompts_added
        # Without a first run the new prompts are saved paused, so nothing is checked until someone turns them on.
        assert AEOPrompt.objects.for_team(self.team.id).filter(active=True).count() == (
            prompts_added if run_first_check else 0
        )
        assert job["steps"][2]["detail"] == ("" if prompts_added == 0 else "fewer" if run_first_check else "paused")
        assert job["steps"][2]["requested"] == (20 if prompts_added else 0)
        assert AEOKeyword.objects.for_team(self.team.id).count() == expected_steps[4][2]
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
            ("research", "skipped"),
            ("prompts", "skipped"),
            ("first_run", "skipped"),
            ("keywords", "skipped"),
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

        job, _, first_run = self._run([*_prompt_answers(), _answer(KEYWORDS_ANSWER)])

        assert self._steps(job)[0] == ("brand", "done", 1)
        assert list(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind", "status")) == [
            ("example.com", BrandKind.OWN, BrandStatus.CONFIRMED)
        ]
        assert first_run.call_count == 1

    def test_setup_saves_the_competitors_it_found_and_queues_the_run_before_keywords(self) -> None:
        AEOBrand.objects.for_team(self.team.id).create(
            team=self.team, name="Shopify", domain="shopify.com", status=BrandStatus.IGNORED, source=BrandSource.MANUAL
        )
        competitors = [
            {"name": "Acme", "domain": "acme.io"},
            {"name": "Shopify", "domain": "shopify.com"},
            {"name": "Example", "domain": "www.example.com"},
        ]

        job, _, _ = self._run(
            [*_prompt_answers({"competitors": competitors, "prompts": PROMPTS_ANSWER}), _answer(KEYWORDS_ANSWER)]
        )

        assert job["status"] == "completed"
        assert sorted(AEOBrand.objects.for_team(self.team.id).values_list("domain", "kind", "status")) == [
            ("acme.io", BrandKind.COMPETITOR, BrandStatus.SUGGESTED),
            ("example.com", BrandKind.OWN, BrandStatus.CONFIRMED),
            ("shopify.com", BrandKind.UNKNOWN, BrandStatus.IGNORED),
        ]
        assert [name for name, _, _ in self.calls.mock_calls] == ["model", "model", "model", "first_run", "model"]

    def test_setup_saves_the_prompts_past_the_limit_paused(self) -> None:
        prompt_limit.set_max_active_prompts(self.team.id, 2)

        job, _, first_run = self._run([*_prompt_answers(), _answer(KEYWORDS_ANSWER)])

        assert job["status"] == "completed"
        assert (self._steps(job)[2], job["steps"][2]["detail"]) == (("prompts", "done", 3), "prompt_limit")
        prompts = AEOPrompt.objects.for_team(self.team.id)
        assert (prompts.filter(active=True).count(), prompts.filter(active=False).count()) == (2, 1)
        assert first_run.call_count == 1

    @parameterized.expand([("room_for_all", 100, 3), ("room_for_one_more", 2, 2)])
    def test_configure_only_keeps_existing_prompts_and_run_once_turns_the_paused_ones_on(
        self, _name: str, limit: int, expected_active: int
    ) -> None:
        prompt_limit.set_max_active_prompts(self.team.id, limit)
        AEOPrompt.objects.for_team(self.team.id).create(
            team=self.team,
            prompt=PROMPTS_ANSWER[0]["prompt"],
            prompt_hash=prompt_hash(PROMPTS_ANSWER[0]["prompt"]),
            prompt_source=AEOPrompt.Source.MANUAL,
        )

        self._run([*_prompt_answers(), _answer(KEYWORDS_ANSWER)], run_first_check=False)

        prompts = AEOPrompt.objects.for_team(self.team.id)
        assert sorted(prompts.values_list("prompt", "active")) == [
            (PROMPTS_ANSWER[0]["prompt"], True),
            (PROMPTS_ANSWER[1]["prompt"], False),
            (PROMPTS_ANSWER[2]["prompt"], False),
        ]
        context = self.client.get(f"{self.url}context/").json()
        assert (context["active_prompts"], context["paused_prompts"], context["max_active_prompts"]) == (1, 2, limit)

        job, post, first_run = self._run([], body={"only_first_run": True, "activate_paused_prompts": True})

        assert self._steps(job)[3] == ("first_run", "done", 0)
        assert post.call_count == 0
        assert first_run.call_count == 1
        assert prompts.filter(active=True).count() == expected_active

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
            ("research", "skipped", "not_requested"),
            ("prompts", "skipped", "not_requested"),
            ("first_run", "done", ""),
            ("keywords", "skipped", "not_requested"),
        ]
        assert post.call_count == 0
        assert first_run.call_count == 1
        assert list_engine_settings(self.team.id) == engines_before

    def test_a_failed_enqueue_fails_only_the_first_run_step(self) -> None:
        job, _, _ = self._run(
            [*_prompt_answers(), _answer(KEYWORDS_ANSWER)], enqueue_error=ConnectionError("broker down")
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

        assert post.call_count == 2
        assert auto_setup.load_job(self.team.id, job.id).error == auto_setup.STALE_JOB_ERROR

    def test_a_second_setup_while_one_runs_returns_the_running_job(self) -> None:
        engines_before = list_engine_settings(self.team.id)

        with patch("products.aeo.backend.facade.api.set_up_aeo_task.apply_async") as queued:
            first = self.client.post(self.url, {"domain": "example.com"}, format="json")
            second = self.client.post(self.url, {"domain": "example.com", "engines": ["exa-answer"]}, format="json")

        assert first.status_code == status.HTTP_202_ACCEPTED
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["job_id"] == first.json()["id"]
        assert queued.call_count == 1
        # The refused request must not leave the running job, or the runs after it, on engines nobody accepted.
        assert list_engine_settings(self.team.id) == engines_before

    @parameterized.expand(
        [
            ("no_ai_consent", False, {"domain": "example.com"}, status.HTTP_403_FORBIDDEN, False),
            ("not_a_domain", True, {"domain": "localhost"}, status.HTTP_400_BAD_REQUEST, False),
            (
                "activation_outside_a_run",
                True,
                {"domain": "example.com", "activate_paused_prompts": True},
                status.HTTP_400_BAD_REQUEST,
                False,
            ),
            ("out_of_ai_credits", True, {"domain": "example.com"}, status.HTTP_402_PAYMENT_REQUIRED, True),
        ]
    )
    def test_setup_refuses_to_start(
        self, _name: str, ai_approved: bool, body: dict, expected: int, out_of_credits: bool
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        with (
            ai_credits_used_up(self.team) if out_of_credits else nullcontext(),
            patch.object(credits, "BILLABLE_AI_PRODUCTS", frozenset({"ai_visibility"})),
            patch("products.aeo.backend.facade.api.set_up_aeo_task.apply_async") as queued,
        ):
            response = self.client.post(self.url, body, format="json")

        assert response.status_code == expected
        assert queued.call_count == 0
        assert AEOBrand.objects.for_team(self.team.id).count() == 0

    @parameterized.expand(
        [
            ("tracks_only_the_chosen_engines", ["exa-answer"], status.HTTP_202_ACCEPTED, {"exa-answer"}),
            (
                "keeps_a_chosen_engine_that_is_not_available_yet",
                ["exa-answer", "claude-web-search"],
                status.HTTP_202_ACCEPTED,
                {"exa-answer", "claude-web-search"},
            ),
            ("unknown_engine", ["exa-answer", "not-an-engine"], status.HTTP_400_BAD_REQUEST, None),
            ("no_engine", [], status.HTTP_400_BAD_REQUEST, None),
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
        # An engine this deployment cannot run yet stays on when chosen; the runner's schedule still skips it.
        assert {s.engine: s.enabled for s in after} == (
            before if enabled is None else {engine: engine in enabled for engine in before}
        )
        with patch("products.aeo.backend.engines.resolve_ai_gateway_config", return_value=None):
            schedule = engine_schedule(self.team.id)
        assert {e.name for e in [*schedule.daily, *schedule.weekly]} <= {"exa-answer"}

    @parameterized.expand([("before the setup", False), ("during the setup", True)])
    def test_a_stop_skips_setups_run_only_when_asked_for_after_setup_started(self, _name: str, during: bool) -> None:
        answers = [*_prompt_answers(), _answer(KEYWORDS_ANSWER)]
        if during:
            answers[0].raise_for_status.side_effect = lambda: run_stop.request_stop(self.team.id)
        else:
            assert self.client.post(f"{self.url}stop_checks/").status_code == status.HTTP_204_NO_CONTENT

        _, _, first_run = self._run(answers)

        first_run.assert_called_once()
        queued_at = first_run.call_args.kwargs["queued_at"]
        assert run_stop.stop_requested(self.team.id, since=queued_at) is during

    def test_a_reset_lets_setup_run_again_for_another_site(self) -> None:
        first, _, _ = self._run(
            [
                *_prompt_answers(
                    {
                        "competitors": [{"name": "Competitor", "domain": "rival.org"}],
                        "prompts": PROMPTS_ANSWER,
                    }
                ),
                _answer(KEYWORDS_ANSWER),
            ]
        )
        assert AEOBrand.objects.for_team(self.team.id).filter(domain="rival.org").exists()
        assert first["status"] == "completed"
        create_citation_check(self.team, "earlier")
        # The first run's task is mocked, so nothing clears the queued marker the way the finished run would.
        run_stop.clear_run_queued(self.team.id)

        assert self.client.post(f"{self.url}reset/").status_code == status.HTTP_204_NO_CONTENT

        kept = [(row.prompt, row.archived_at is not None) for row in AEOPrompt.objects.for_team(self.team.id)]
        assert kept == [("is earlier cited?", True)]
        assert not AEOKeyword.objects.for_team(self.team.id).exists()
        assert catalog.own_domains(self.team.id) == []
        assert (
            not AEOBrand.objects.for_team(self.team.id)
            .filter(status=BrandStatus.SUGGESTED, kind=BrandKind.COMPETITOR)
            .exists()
        )
        assert not AEOBrand.objects.for_team(self.team.id).filter(domain="rival.org").exists()
        second, _, second_run = self._run(
            [*_prompt_answers(), _answer(KEYWORDS_ANSWER)], body={"domain": "example.org", "run_first_check": True}
        )
        assert self._steps(second)[:4] == [
            ("brand", "done", 1),
            ("research", "done", 0),
            ("prompts", "done", 3),
            ("first_run", "done", 0),
        ]
        assert catalog.own_domains(self.team.id) == ["example.org"]
        second_run.assert_called_once()

    def test_a_reset_keeps_a_prompt_a_person_edited_with_its_history(self) -> None:
        self._run([*_prompt_answers(), _answer(KEYWORDS_ANSWER)])
        run_stop.clear_run_queued(self.team.id)
        edited, *untouched = AEOPrompt.objects.for_team(self.team.id).order_by("prompt")
        prompts_url = f"/api/projects/{self.team.id}/aeo_prompts/"
        assert (
            self.client.patch(f"{prompts_url}{edited.id}/", {"prompt": "Reworded?"}, format="json").status_code == 200
        )

        assert self.client.post(f"{self.url}reset/").status_code == status.HTTP_204_NO_CONTENT

        prompts = AEOPrompt.objects.for_team(self.team.id)
        assert list(prompts.values_list("id", flat=True)) == [edited.id]
        assert prompts.get().archived_at is not None
        assert AEOPromptVersion.objects.for_team(self.team.id).filter(prompt_id=edited.id).count() == 2
        assert untouched

    def test_a_reset_during_a_check_run_stops_it_and_archives_the_prompts_it_writes_against(self) -> None:
        self._run([*_prompt_answers(), _answer(KEYWORDS_ANSWER)])
        written = set(AEOPrompt.objects.for_team(self.team.id).values_list("id", flat=True))
        assert written
        run_stop.mark_run_queued(self.team.id)

        assert self.client.post(f"{self.url}reset/").status_code == status.HTTP_204_NO_CONTENT

        prompts = AEOPrompt.objects.for_team(self.team.id)
        assert set(prompts.values_list("id", flat=True)) == written
        assert not prompts.filter(archived_at__isnull=True).exists()
        assert run_stop.stop_requested(self.team.id)
        # The reset held the setup slot only while it ran.
        assert auto_setup.running_job_id(self.team.id) is None

    def test_a_job_cancelled_during_research_asks_for_no_keywords(self) -> None:
        def cancel() -> None:
            job_id = auto_setup.running_job_id(self.team.id)
            assert self.client.post(f"{self.url}{job_id}/cancel/").json()["status"] == "cancelled"

        answers = [*_prompt_answers(), _answer(KEYWORDS_ANSWER)]
        answers[0].raise_for_status.side_effect = cancel
        pool = MagicMock()

        with patch.object(auto_setup, "_keyword_pool", return_value=pool):
            job, post, _ = self._run(answers)

        assert job["status"] == "cancelled"
        # Only the research call was paid for: no keyword call was even handed to the pool after the cancel.
        assert post.call_count == 1
        pool.submit.assert_not_called()

    def test_cancelling_a_finished_job_stops_no_run(self) -> None:
        job, _, _ = self._run([*_prompt_answers(), _answer(KEYWORDS_ANSWER)])
        assert job["status"] == "completed"

        cancelled = self.client.post(f"{self.url}{job['id']}/cancel/")

        assert cancelled.json()["status"] == "completed"
        assert not run_stop.stop_requested(self.team.id)

    def test_a_cancel_during_a_progress_save_is_kept(self) -> None:
        job = auto_setup.create_job(self.team.id)
        progress = auto_setup._Progress(self.team.id, job.id, time.time())
        read = auto_setup._read
        cancel = threading.Thread(target=auto_setup.cancel_job, args=(self.team.id, job.id))

        def read_then_cancel(team_id: int, job_id: str) -> Any:
            result = read(team_id, job_id)
            if not cancel.is_alive() and cancel.ident is None:
                cancel.start()
                # The cancel waits on the save's lock; without the lock it would land before the save's write.
                cancel.join(timeout=0.5)
            return result

        with patch.object(auto_setup, "_read", side_effect=read_then_cancel):
            progress.set(auto_setup.SetupStep.BRAND, auto_setup.SetupStepStatus.RUNNING)
        cancel.join()

        assert auto_setup.load_job(self.team.id, job.id).status == "cancelled"

    def test_a_job_cancelled_while_writing_prompts_saves_nothing_more(self) -> None:
        def cancel() -> None:
            job_id = auto_setup.running_job_id(self.team.id)
            assert self.client.post(f"{self.url}{job_id}/cancel/").json()["status"] == "cancelled"

        research, written, top_up = _prompt_answers()
        written.raise_for_status.side_effect = cancel

        job, post, first_run = self._run([research, written, top_up, _answer(KEYWORDS_ANSWER)])

        assert job["status"] == "cancelled"
        assert self._steps(job)[:3] == [("brand", "done", 1), ("research", "done", 0), ("prompts", "skipped", 0)]
        assert not AEOPrompt.objects.for_team(self.team.id).exists()
        assert not AEOKeyword.objects.for_team(self.team.id).exists()
        assert first_run.call_count == 0
        assert run_stop.stop_requested(self.team.id)

    def test_context_counts_the_first_run_of_the_prompts_that_are_on(self) -> None:
        create_citation_check(self.team, "earlier")
        AEOPrompt.objects.for_team(self.team.id).update(archived_at=timezone.now(), active=False)
        create_citation_check(self.team, "current")
        run_stop.mark_run_queued(self.team.id)

        context = self.client.get(f"{self.url}context/").json()

        assert context["first_run_checks"] == [{"engine": "exa-answer", "checks": 1}]
        assert context["checks_running"] is True
        run_stop.clear_run_queued(self.team.id)
        assert self.client.get(f"{self.url}context/").json()["checks_running"] is False

    def test_keywords_are_picked_while_the_prompts_are_written(self) -> None:
        research, written, top_up = _prompt_answers()
        keyword_call_started = threading.Event()
        overlapped: list[bool] = []

        def post(*args: Any, **kwargs: Any) -> MagicMock:
            instructions = kwargs["json"]["messages"][0]["content"]
            if instructions.startswith("You research a company"):
                return research
            if "choose the keywords" in instructions:
                keyword_call_started.set()
                return _answer(KEYWORDS_ANSWER)
            # The prompt call holds until the keyword call has started, which only happens if both run at once.
            overlapped.append(keyword_call_started.wait(timeout=10))
            return written if len(overlapped) == 1 else top_up

        with patch("products.aeo.backend.auto_setup._keyword_pool", return_value=ThreadPoolExecutor(max_workers=1)):
            job, _, _ = self._run(post)

        assert overlapped[0] is True
        assert self._steps(job)[2:] == [("prompts", "done", 3), ("first_run", "done", 0), ("keywords", "done", 1)]

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
