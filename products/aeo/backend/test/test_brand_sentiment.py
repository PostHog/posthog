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

from products.aeo.backend.engines import CitationCheck, own_domains_key
from products.aeo.backend.facade.contracts import BrandKind, BrandSource, BrandStatus, CheckMode
from products.aeo.backend.models import AEOBrand, AEOCheckBrand, AEOCitationCheck, AEOPrompt
from products.aeo.backend.runner import run_citation_checks
from products.aeo.backend.seeding import PromptCandidate, upsert_prompts
from products.aeo.backend.sentiment import UNSCORABLE
from products.aeo.backend.temporal.brand_sentiment import AEOBrandSentimentInputs, classify_aeo_brand_sentiment
from products.aeo.backend.test.factories import create_own_brand, store_what_the_runner_stores

_MODULE = "products.aeo.backend.temporal.brand_sentiment"
_CURRENT_KEY = own_domains_key(["example.com"])


def _team() -> Team:
    organization = Organization.objects.create(name="aeo sentiment org")
    return Team.objects.create(organization=organization, name="aeo sentiment team")


def _check(team: Team, prompt: AEOPrompt, run_id: uuid.UUID, answer_text: str | None, **fields) -> AEOCitationCheck:
    fields.setdefault("own_domains_key", _CURRENT_KEY)
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
        "scored": _check(
            team,
            prompt,
            run_id,
            "Example again.",
            brand_sentiment="neutral",
            brand_sentiment_score=0.5,
            brand_sentiment_sentences=[{"start": 0, "end": 14, "label": "neutral", "score": 0.5}],
        ),
        "other_run": _check(team, prompt, uuid.uuid4(), "Example elsewhere."),
        "no_brand_backlog": _check(team, prompt, uuid.uuid4(), "Rival elsewhere."),
        "too_old": _check(team, prompt, uuid.uuid4(), "Example long ago."),
        # Waits for the own-citation reconcile, which re-keys it.
        "stale_key": _check(team, prompt, run_id, "Example is stale.", own_domains_key=own_domains_key(["old.com"])),
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
    team = await sync_to_async(_team)()
    await sync_to_async(create_own_brand)(team, "example.com")
    run_id, checks = await sync_to_async(_seed_run)(team)
    await sync_to_async(_age)(checks["other_run"], 10)
    await sync_to_async(_age)(checks["no_brand_backlog"], 20)
    await sync_to_async(_age)(checks["too_old"], 31)
    classify = MagicMock(
        side_effect=[
            [_result(positive=0.9, neutral=0.08, negative=0.02)],
            [_result(positive=0.05, neutral=0.15, negative=0.8), _result(positive=0.75, neutral=0.2, negative=0.05)],
            [_result(positive=0.1, neutral=0.85, negative=0.05)],
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

    assert result == {"scored": 3, "answers": 3, "brands_scored": 0}
    assert [call.args[0] for call in classify.call_args_list] == [
        ["Example is fast."],
        ["Example is slow.", "Still, Example is cheap."],
        ["Example elsewhere."],
    ]

    def sentiments() -> dict[str, tuple[str | None, float | None]]:
        with team_scope(team.pk):
            rows = AEOCitationCheck.objects.in_bulk([check.id for check in checks.values()])
        return {
            name: (rows[check.id].brand_sentiment, rows[check.id].brand_sentiment_score)
            for name, check in checks.items()
        }

    def sentences(name: str) -> list[tuple[str, str, float]] | None:
        with team_scope(team.pk):
            check = AEOCitationCheck.objects.get(id=checks[name].id)
        if check.brand_sentiment_sentences is None:
            return None
        return [
            ((check.answer_text or "")[sentence["start"] : sentence["end"]], sentence["label"], sentence["score"])
            for sentence in check.brand_sentiment_sentences
        ]

    assert await sync_to_async(sentences)("two_sentences") == [
        ("Example is slow.", "negative", 0.8),
        ("Still, Example is cheap.", "positive", 0.75),
    ]
    assert await sync_to_async(sentences)("no_brand") is None
    assert await sync_to_async(sentiments)() == {
        "praise": ("positive", 0.9),
        "two_sentences": ("negative", 0.425),
        "no_brand": (None, None),
        "failed": (None, None),
        "scored": ("neutral", 0.5),
        "other_run": ("neutral", 0.85),
        "no_brand_backlog": (None, None),
        "too_old": (None, None),
        "stale_key": (None, None),
    }


def _seed_competitor_answers(team: Team) -> tuple[uuid.UUID, AEOCitationCheck, AEOCitationCheck]:
    create_own_brand(team, "example.com")
    with team_scope(team.pk):
        AEOBrand.objects.create(
            team=team,
            name="Rival",
            domain="rival.io",
            kind=BrandKind.COMPETITOR,
            status=BrandStatus.CONFIRMED,
            source=BrandSource.MANUAL,
        )
        prompt = AEOPrompt.objects.create(
            team=team, prompt="best tool?", prompt_hash="h", prompt_source=AEOPrompt.Source.MANUAL
        )
    run_id = uuid.uuid4()
    recent = _check(team, prompt, run_id, "Example is fast. Rival is slow and pricey.")
    old = _check(team, prompt, uuid.uuid4(), "Rival long ago.")
    _age(old, 31)
    for check in (recent, old):
        store_what_the_runner_stores(check.id)
    return run_id, recent, old


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_activity_scores_each_other_brand_on_the_sentences_that_name_it(settings) -> None:
    team = await sync_to_async(_team)()
    run_id, recent, old = await sync_to_async(_seed_competitor_answers)(team)
    classify = MagicMock(
        side_effect=[
            [_result(positive=0.9, neutral=0.08, negative=0.02)],
            [_result(positive=0.05, neutral=0.15, negative=0.8)],
        ]
    )

    with patch("posthog.temporal.ai_observability.sentiment.model.classify", classify):
        result = await ActivityEnvironment().run(
            classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id, run_id=str(run_id))
        )

    assert result == {"scored": 1, "answers": 1, "brands_scored": 1}
    # The own brand's sentence and the competitor's are classified apart, so praise of one is never the other's.
    assert [call.args[0] for call in classify.call_args_list] == [["Example is fast."], ["Rival is slow and pricey."]]

    def brand_sentiments() -> set[tuple[str, str, str | None]]:
        with team_scope(team.pk):
            rows = AEOCheckBrand.objects.filter(team=team).values_list(
                "citation_check_id", "brand__domain", "sentiment"
            )
        names = {recent.id: "recent", old.id: "old"}
        return {(names[check_id], domain, sentiment) for check_id, domain, sentiment in rows}

    # The own brand's row stays empty, because its sentiment is on the check, and the old answer is past the window.
    assert await sync_to_async(brand_sentiments)() == {
        ("recent", "example.com", None),
        ("recent", "rival.io", "negative"),
        ("old", "rival.io", None),
    }


def _seed_an_unscorable_row_before_a_scorable_one(team: Team) -> tuple[AEOCitationCheck, AEOCitationCheck]:
    _, recent, _ = _seed_competitor_answers(team)
    with team_scope(team.pk):
        prompt = AEOPrompt.objects.get(team=team)
    blocked = _check(team, prompt, uuid.uuid4(), "Rival is fine.")
    _age(blocked, 2)
    store_what_the_runner_stores(blocked.id)
    # A stored mention whose offset no longer reads as its surface has no sentence to score.
    with team_scope(team.pk):
        AEOCheckBrand.objects.filter(team=team, citation_check=blocked).update(
            mentions=[{"surface": "Rival", "kind": "name", "start": 40}]
        )
    return blocked, recent


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_unscorable_brand_rows_are_marked_so_the_backlog_moves_past_them(settings) -> None:
    team = await sync_to_async(_team)()
    blocked, recent = await sync_to_async(_seed_an_unscorable_row_before_a_scorable_one)(team)
    classify = MagicMock(return_value=[_result(positive=0.05, neutral=0.15, negative=0.8)])

    def rival_sentiments() -> dict[str, str | None]:
        with team_scope(team.pk):
            rows = AEOCheckBrand.objects.filter(
                team=team, brand__domain="rival.io", citation_check__in=[blocked, recent]
            )
            return {
                ("blocked" if row.citation_check_id == blocked.id else "recent"): row.sentiment
                for row in rows.only("citation_check_id", "sentiment")
            }

    # With one row per pass, the oldest row is the unscorable one. The first pass marks it, the second scores the next.
    with (
        patch("posthog.temporal.ai_observability.sentiment.model.classify", classify),
        patch(f"{_MODULE}.MAX_ROWS_PER_RUN", 1),
    ):
        for _ in range(2):
            await ActivityEnvironment().run(classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id))

    assert await sync_to_async(rival_sentiments)() == {"blocked": UNSCORABLE, "recent": "negative"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_pass_without_a_run_scores_the_whole_recent_backlog(settings) -> None:
    team = await sync_to_async(_team)()
    await sync_to_async(create_own_brand)(team, "example.com")
    _, checks = await sync_to_async(_seed_run)(team)
    await sync_to_async(_age)(checks["other_run"], 10)
    await sync_to_async(_age)(checks["too_old"], 31)
    # Scored before the sentences were stored: it has a label and no sentences.
    label_only = await sync_to_async(_check)(
        team,
        checks["praise"].prompt,
        uuid.uuid4(),
        "Example before sentences.",
        brand_sentiment="negative",
        brand_sentiment_score=0.7,
    )
    await sync_to_async(_age)(label_only, 20)
    classify = MagicMock(side_effect=lambda texts: [_result(positive=0.6, neutral=0.3, negative=0.1) for _ in texts])

    with patch("posthog.temporal.ai_observability.sentiment.model.classify", classify):
        result = await ActivityEnvironment().run(
            classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id, run_id=None)
        )

    assert result == {"scored": 4, "answers": 4, "brands_scored": 0}
    assert [sentence for call in classify.call_args_list for sentence in call.args[0]] == [
        "Example before sentences.",
        "Example elsewhere.",
        "Example is fast.",
        "Example is slow.",
        "Still, Example is cheap.",
    ]
    rescored = await sync_to_async(
        lambda: (
            AEOCitationCheck.objects.for_team(team.id)
            .values_list("brand_sentiment", "brand_sentiment_sentences")
            .get(id=label_only.id)
        )
    )()
    assert rescored == ("positive", [{"start": 0, "end": 25, "label": "positive", "score": 0.6}])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_pass_that_runs_out_of_time_keeps_the_scores_it_finished(settings) -> None:
    team = await sync_to_async(_team)()
    await sync_to_async(create_own_brand)(team, "example.com")
    _, checks = await sync_to_async(_seed_run)(team)
    await sync_to_async(_age)(checks["other_run"], 10)
    classify = MagicMock(side_effect=lambda texts: [_result(positive=0.6, neutral=0.3, negative=0.1) for _ in texts])

    with (
        patch("posthog.temporal.ai_observability.sentiment.model.classify", classify),
        patch(f"{_MODULE}.SCORING_BUDGET", dt.timedelta(0)),
    ):
        result = await ActivityEnvironment().run(
            classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id, run_id=None)
        )

    assert result == {"scored": 1, "answers": 1, "brands_scored": 0}

    def labels() -> dict[str, str | None]:
        with team_scope(team.pk):
            rows = AEOCitationCheck.objects.in_bulk([checks[name].id for name in ("other_run", "praise")])
        return {name: rows[checks[name].id].brand_sentiment for name in ("other_run", "praise")}

    assert await sync_to_async(labels)() == {"other_run": "positive", "praise": None}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_activity_drops_scores_of_checks_re_keyed_while_the_model_ran(settings) -> None:
    team = await sync_to_async(_team)()
    await sync_to_async(create_own_brand)(team, "example.com")
    run_id, checks = await sync_to_async(_seed_run)(team)
    re_keyed = checks["praise"]

    def reconcile_meanwhile(texts: list[str]) -> list[SentimentResult]:
        with team_scope(team.pk):
            AEOCitationCheck.objects.filter(id=re_keyed.id).update(own_domains_key=own_domains_key(["new.com"]))
        return [_result(positive=0.9, neutral=0.08, negative=0.02) for _ in texts]

    with patch("posthog.temporal.ai_observability.sentiment.model.classify", reconcile_meanwhile):
        result = await ActivityEnvironment().run(
            classify_aeo_brand_sentiment, AEOBrandSentimentInputs(team_id=team.id, run_id=str(run_id))
        )

    assert result["scored"] == result["answers"] - 1
    scored = await sync_to_async(
        lambda: AEOCitationCheck.objects.for_team(team.id).values_list("brand_sentiment", flat=True).get(id=re_keyed.id)
    )()
    assert scored is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ImportError("No module named 'onnxruntime'"), FileNotFoundError("model.onnx")])
async def test_activity_leaves_rows_unscored_when_the_model_is_unavailable(settings, error: Exception) -> None:
    team = await sync_to_async(_team)()
    await sync_to_async(create_own_brand)(team, "example.com")
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
    mode = CheckMode.WEB_SEARCH

    def run(self, prompt: str, *, trace_id: str, custom_properties: dict[str, str]) -> CitationCheck:
        return CitationCheck(engine=self.name, model=self.model, answer_text="Example is fine.")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "record, expected_starts",
    [(True, 1), (False, 0)],
    ids=["recording", "dry_run"],
)
def test_runner_starts_the_sentiment_workflow_only_when_recording(settings, record: bool, expected_starts: int) -> None:
    team = _team()
    create_own_brand(team, "example.com")
    upsert_prompts(team, [PromptCandidate(text="q?", source="imported")])

    with patch(f"{_MODULE}.sync_connect") as connect, patch(f"{_MODULE}.asyncio.run") as run:
        summary, _ = run_citation_checks(team, engines=[_StubEngine()], record=record)

    assert summary.rows_written == (1 if record else 0)
    assert run.call_count == expected_starts
    if expected_starts:
        start = connect.return_value.start_workflow
        start.assert_called_once()
        assert start.call_args.kwargs["id"] == f"aeo-brand-sentiment-{team.id}-{summary.run_id}"
        assert start.call_args.kwargs["task_queue"] == settings.AEO_TASK_QUEUE
