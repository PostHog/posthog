import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models.organization import Organization
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.temporal.ai_observability.sentiment.schema import SentimentResult

from products.aeo.backend.engines import CitationCheck
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.runner import run_citation_checks
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts
from products.aeo.backend.temporal.brand_sentiment import AEOBrandSentimentInputs, classify_aeo_brand_sentiment

_MODULE = "products.aeo.backend.temporal.brand_sentiment"


def _team() -> Team:
    organization = Organization.objects.create(name="aeo sentiment org")
    return Team.objects.create(organization=organization, name="aeo sentiment team")


def _check(team: Team, prompt: AEOPrompt, run_id: uuid.UUID, answer_text: str | None, **fields) -> AEOCitationCheck:
    with team_scope(team.pk):
        return AEOCitationCheck.objects.create(
            team=team,
            prompt=prompt,
            run_id=run_id,
            prompt_text=prompt.prompt,
            prompt_source=prompt.prompt_source,
            prompt_hash=prompt.prompt_hash,
            engine="exa-answer",
            model="exa-answer",
            answer_text=answer_text,
            **fields,
        )


def _seed_run(team: Team) -> tuple[uuid.UUID, dict[str, AEOCitationCheck]]:
    with team_scope(team.pk):
        prompt = AEOPrompt.objects.create(
            team=team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )
    run_id = uuid.uuid4()
    return run_id, {
        "praise": _check(team, prompt, run_id, "Example is fast. Rival is slow."),
        "two_sentences": _check(team, prompt, run_id, "Example is slow. Still, Example is cheap."),
        "no_brand": _check(team, prompt, run_id, "Rival is the only option."),
        "failed": _check(team, prompt, run_id, None, check_failed=True),
        "scored": _check(team, prompt, run_id, "Example again.", brand_sentiment="neutral", brand_sentiment_score=0.5),
        "other_run": _check(team, prompt, uuid.uuid4(), "Example elsewhere."),
        "no_brand_backlog": _check(team, prompt, uuid.uuid4(), "Rival elsewhere."),
        "too_old": _check(team, prompt, uuid.uuid4(), "Example long ago."),
    }


def _age(check: AEOCitationCheck, days: int) -> None:
    with team_scope(check.team_id):
        AEOCitationCheck.objects.filter(id=check.id).update(created_at=timezone.now() - dt.timedelta(days=days))


def _result(**scores: float) -> SentimentResult:
    label = max(scores, key=scores.__getitem__)
    return SentimentResult(label=label, score=scores[label], scores=scores)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_activity_scores_the_runs_answers_then_the_recent_unscored_backlog(settings) -> None:
    settings.AEO_TARGET_DOMAINS = ["example.com"]
    team = await sync_to_async(_team)()
    run_id, checks = await sync_to_async(_seed_run)(team)
    await sync_to_async(_age)(checks["other_run"], 10)
    await sync_to_async(_age)(checks["no_brand_backlog"], 20)
    await sync_to_async(_age)(checks["too_old"], 31)
    classify = MagicMock(
        return_value=[
            _result(positive=0.9, neutral=0.08, negative=0.02),
            _result(positive=0.05, neutral=0.15, negative=0.8),
            _result(positive=0.75, neutral=0.2, negative=0.05),
            _result(positive=0.1, neutral=0.85, negative=0.05),
        ]
    )

    # Cap of 4 leaves one backlog slot after the run's own rows. The older brand-less backlog row
    # must not take it from the newer answer that names the brand.
    with (
        patch("posthog.temporal.ai_observability.sentiment.model.classify", classify),
        patch(f"{_MODULE}.MAX_ROWS_PER_RUN", 4),
    ):
        result = await ActivityEnvironment().run(
            classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id, run_id=str(run_id))
        )

    assert result == {"scored": 3, "answers": 3}
    classify.assert_called_once_with(
        ["Example is fast.", "Example is slow.", "Still, Example is cheap.", "Example elsewhere."]
    )

    def sentiments() -> dict[str, tuple[str | None, float | None]]:
        with team_scope(team.pk):
            rows = AEOCitationCheck.objects.in_bulk([check.id for check in checks.values()])
        return {
            name: (rows[check.id].brand_sentiment, rows[check.id].brand_sentiment_score)
            for name, check in checks.items()
        }

    assert await sync_to_async(sentiments)() == {
        "praise": ("positive", 0.9),
        "two_sentences": ("negative", 0.425),
        "no_brand": (None, None),
        "failed": (None, None),
        "scored": ("neutral", 0.5),
        "other_run": ("neutral", 0.85),
        "no_brand_backlog": (None, None),
        "too_old": (None, None),
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ImportError("No module named 'onnxruntime'"), FileNotFoundError("model.onnx")])
async def test_activity_leaves_rows_unscored_when_the_model_is_unavailable(settings, error: Exception) -> None:
    settings.AEO_TARGET_DOMAINS = ["example.com"]
    team = await sync_to_async(_team)()
    run_id, checks = await sync_to_async(_seed_run)(team)

    with patch("posthog.temporal.ai_observability.sentiment.model.classify", MagicMock(side_effect=error)):
        result = await ActivityEnvironment().run(
            classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id, run_id=str(run_id))
        )

    assert result == {"scored": 0, "answers": 4, "error": "model_unavailable"}
    unscored = await sync_to_async(
        lambda: AEOCitationCheck.objects.for_team(team.id).filter(brand_sentiment__isnull=True).count()
    )()
    assert unscored == len(checks) - 1


class _StubEngine:
    name = "stub-engine"
    model = "stub"

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        return CitationCheck(engine=self.name, model=self.model, answer_text="Example is fine.")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "enabled, record, expected_starts",
    [(True, True, 1), (False, True, 0), (True, False, 0)],
    ids=["on", "off", "dry_run"],
)
def test_runner_starts_the_sentiment_workflow_only_when_enabled_and_recording(
    settings, enabled: bool, record: bool, expected_starts: int
) -> None:
    settings.AEO_BRAND_SENTIMENT_ENABLED = enabled
    team = _team()
    upsert_prompts(team, [PromptCandidate(text="q?", source="imported")])

    with patch(f"{_MODULE}.sync_connect") as connect, patch(f"{_MODULE}.asyncio.run") as run:
        summary, _ = run_citation_checks(team, engines=[_StubEngine()], record=record)

    assert summary.rows_written == (1 if record else 0)
    assert run.call_count == expected_starts
    if expected_starts:
        start = connect.return_value.start_workflow
        start.assert_called_once()
        assert start.call_args.kwargs["id"] == f"aeo-brand-sentiment-{team.id}-{summary.run_id}"
        assert start.call_args.kwargs["task_queue"] == settings.LLMA_EVALS_TASK_QUEUE
