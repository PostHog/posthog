import asyncio

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.evals.constants import BLOCKER_TYPES, EVAL_OUTCOMES, TICKET_TYPES
from products.conversations.evals.fixtures import FIXTURES, FIXTURES_BY_NAME, expected_for
from products.conversations.evals.outcomes import eval_outcome_from_triage
from products.conversations.evals.runner import run_fixture
from products.conversations.evals.scorers import (
    CitationPrecision,
    ClarifyingQuestion,
    CostScorer,
    ForbiddenClaims,
    Grounding,
    OutcomeMatch,
)
from products.conversations.evals.seeders import provision_eval_team, seed_case, teardown_eval_team
from products.posthog_ai.eval_harness.scorers.contract import Score


class TestEvalOutcomeFromTriage(SimpleTestCase):
    @parameterized.expand(
        [
            ("persisted_is_answerable", {"status": "done", "result": "persisted"}, "answerable"),
            ("escalated_with_best", {"status": "done", "result": "escalated_with_best"}, "escalate"),
            ("suggested_is_escalate", {"status": "done", "result": "suggested"}, "escalate"),
            ("findings_is_escalate", {"status": "done", "result": "escalated_with_findings"}, "escalate"),
            (
                "customer_info_blocker_is_clarification",
                {"status": "done", "result": "escalated_with_findings", "blocker": "customer_info"},
                "needs_clarification",
            ),
            ("skipped_unactionable", {"status": "done", "result": "skipped_unactionable"}, "escalate"),
            ("unknown_result_is_unscored", {"status": "done", "result": "mystery"}, None),
            (
                "clarification_status_wins",
                {"status": "awaiting_clarification", "result": "persisted"},
                "needs_clarification",
            ),
            ("unfinished_run", {"status": "in_progress"}, None),
            (
                "unfinished_run_keeps_stale_blocker_unscored",
                {"status": "in_progress", "blocker": "customer_info", "verdict": "blocked_on_customer"},
                None,
            ),
            (
                "blocked_on_customer_verdict_is_clarification",
                {"status": "done", "result": "escalated_with_findings", "verdict": "blocked_on_customer"},
                "needs_clarification",
            ),
            (
                "clarified_result_is_clarification",
                {"status": "awaiting_clarification", "result": "clarified"},
                "needs_clarification",
            ),
            (
                "suggested_clarification_result",
                {"status": "done", "result": "suggested_clarification"},
                "needs_clarification",
            ),
        ]
    )
    def test_maps_triage(self, _name, triage, expected):
        assert eval_outcome_from_triage(triage) == expected


class TestSupportReplyScorers(SimpleTestCase):
    def test_outcome_match_scores_equality(self):
        expected = {"outcome_match": {"outcome": "answerable"}}
        assert OutcomeMatch()._run_eval_sync({"eval_outcome": "answerable"}, expected).score == 1.0
        assert OutcomeMatch()._run_eval_sync({"eval_outcome": "escalate"}, expected).score == 0.0
        assert (
            OutcomeMatch()._run_eval_sync({"eval_outcome": None}, {"outcome_match": {"outcome": "escalate"}}).score
            == 0.0
        )

    def test_citation_precision_skips_when_no_expected_sources(self):
        score = CitationPrecision()._run_eval_sync(
            {"citation_source_names": ["JavaScript SDK install"]},
            {"citation_precision": {"source_names": []}},
        )
        assert score.score is None

    def test_citation_precision_is_hits_over_cited(self):
        score = CitationPrecision()._run_eval_sync(
            {"citation_source_names": ["JavaScript SDK install", "Invoices and billing"]},
            {"citation_precision": {"source_names": ["JavaScript SDK install"]}},
        )
        assert score.score == 0.5

    def test_forbidden_claims_are_case_insensitive(self):
        expected = {"forbidden_claims": {"phrases": ["I'll refund"]}}
        hit = ForbiddenClaims()._run_eval_sync({"reply": "Sure, i'll refund this."}, expected)
        miss = ForbiddenClaims()._run_eval_sync({"reply": "Download the invoice PDF."}, expected)
        assert hit.score == 0.0
        assert miss.score == 1.0

    def test_cost_fails_when_llm_calls_missing_or_not_int(self):
        expected: dict[str, dict[str, object]] = {"cost": {}}
        missing = CostScorer()._run_eval_sync({"cost": {"sandbox_seconds": 1.2}}, expected)
        coerced = CostScorer()._run_eval_sync({"cost": {"sandbox_seconds": 1.2, "llm_calls": 3.0}}, expected)
        ok = CostScorer()._run_eval_sync({"cost": {"sandbox_seconds": 0.0, "llm_calls": 5}}, expected)
        assert missing.score == 0.0
        assert coerced.score == 0.0
        assert ok.score == 1.0

    def test_grounding_skips_unless_required(self):
        prepared = Grounding()._prepare({"reply": "hello"}, expected_for(FIXTURES_BY_NAME["how_to_events_missing_sdk"]))
        assert isinstance(prepared, Score)
        assert prepared.score is None

    def test_grounding_fails_empty_reply_when_required(self):
        prepared = Grounding()._prepare({"reply": ""}, expected_for(FIXTURES_BY_NAME["how_to_sdk_install"]))
        assert isinstance(prepared, Score)
        assert prepared.score == 0.0

    def test_clarifying_question_uses_reply_question_mark(self):
        prepared = ClarifyingQuestion()._prepare(
            {"prompt": "Events aren't showing up.", "reply": "Which SDK are you using?"},
            expected_for(FIXTURES_BY_NAME["how_to_events_missing_sdk"]),
        )
        assert isinstance(prepared, dict)
        assert "Which SDK" in prepared["output"]["questions"]

    def test_clarifying_question_fails_without_a_question(self):
        prepared = ClarifyingQuestion()._prepare(
            {"prompt": "It's broken.", "reply": "I cannot help with that."},
            expected_for(FIXTURES_BY_NAME["how_to_events_missing_sdk"]),
        )
        assert isinstance(prepared, Score)
        assert prepared.score == 0.0


class TestFixtureCoverage(SimpleTestCase):
    def test_every_ticket_type_and_blocker_has_a_fixture(self):
        assert {fixture.ticket_type for fixture in FIXTURES} == set(TICKET_TYPES)
        assert {fixture.blocker for fixture in FIXTURES} == set(BLOCKER_TYPES)
        assert {fixture.expected_outcome for fixture in FIXTURES} == set(EVAL_OUTCOMES)
        assert len({fixture.name for fixture in FIXTURES}) == len(FIXTURES)
        assert FIXTURES_BY_NAME["how_to_sdk_install_posthog"].docs_source == "posthog"
        assert FIXTURES_BY_NAME["how_to_sdk_install"].docs_source is None


@pytest.mark.django_db
def test_seed_case_applies_docs_source():
    fixture = FIXTURES_BY_NAME["how_to_sdk_install_posthog"]
    eval_team = provision_eval_team(label="pytest-docs-source")
    try:
        seed_case(eval_team=eval_team, fixture=fixture)
        eval_team.team.refresh_from_db()
        assert eval_team.team.conversations_settings["docs_source"] == "posthog"
    finally:
        teardown_eval_team(eval_team=eval_team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mocked_runner_persists_answerable_fixture_and_cost():
    fixture = FIXTURES_BY_NAME["how_to_sdk_install"]
    eval_team = await asyncio.to_thread(lambda: provision_eval_team(label="pytest-sdk"))
    try:
        seed = await asyncio.to_thread(lambda: seed_case(eval_team=eval_team, fixture=fixture))
        output = await run_fixture(fixture, seed, live=False)
        assert output.get("error") is None
        assert output["eval_outcome"] == "answerable"
        assert "JavaScript SDK install" in output["citation_source_names"]
        excerpts = output["source_excerpts"]
        assert excerpts
        assert any("YOUR_PROJECT_TOKEN" in (item.get("excerpt") or "") for item in excerpts)
        assert output["cost"]["llm_calls"] == 5
        assert output["cost"]["sandbox_seconds"] == 0.0
        scores = {
            scorer._name(): scorer._run_eval_sync(output, expected_for(fixture))
            for scorer in (OutcomeMatch(), CitationPrecision(), ForbiddenClaims(), CostScorer())
        }
        assert scores["outcome_match"].score == 1.0
        assert scores["citation_precision"].score == 1.0
        assert scores["forbidden_claims"].score == 1.0
        assert scores["cost"].score == 1.0
    finally:
        await asyncio.to_thread(lambda: teardown_eval_team(eval_team=eval_team))
