from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.survey_feedback import (
    SurveyAnswerKind,
    SurveyWindow,
    ThumbsCount,
    answer_kind,
    count_thumbs,
    survey_window,
)
from products.ai_observability.backend.logic.traces.trace_queries import FeedbackEventRow
from products.surveys.backend.facade.api import LinkedSurveyAnswer, LinkedSurveyResponse, RatingScale, SurveyRef

from .rows import T0, make_feedback_row

THUMBS = RatingScale(scale=2, display="emoji", lower_bound_label=None, upper_bound_label=None)


def make_answer(
    question_type: str, value: str | tuple[str, ...], rating: RatingScale | None = None
) -> LinkedSurveyAnswer:
    return LinkedSurveyAnswer(
        question_id="q-1",
        question_index=0,
        question_text="Was this answer useful?",
        question_type=question_type,
        rating=rating,
        value=value,
    )


def make_response(*answers: LinkedSurveyAnswer, minute: int = 0) -> LinkedSurveyResponse:
    return LinkedSurveyResponse(
        survey=SurveyRef(id="survey-1", name="Answer quality"),
        submission_id=f"sub-{minute}",
        submitted_at=T0 + timedelta(minutes=minute),
        complete=True,
        answers=answers,
        unavailable=None,
    )


@parameterized.expand(
    [
        ("a 2-point emoji rating", "rating", THUMBS, "1", "thumbs"),
        (
            "a 2-point number rating",
            "rating",
            RatingScale(scale=2, display="number", lower_bound_label=None, upper_bound_label=None),
            "2",
            "thumbs",
        ),
        ("a 2-point rating with another value", "rating", THUMBS, "3", "rating"),
        (
            "a 5-point rating",
            "rating",
            RatingScale(scale=5, display="number", lower_bound_label="Bad", upper_bound_label="Great"),
            "4",
            "rating",
        ),
        ("a single choice", "single_choice", None, "Accuracy", "choice"),
        ("a multiple choice", "multiple_choice", None, ("Accuracy", "Tone"), "choice"),
        ("an open question", "open", None, "Too long", "text"),
        ("a link question", "link", None, "https://example.com", "text"),
    ]
)
def test_answer_kind(
    _name: str,
    question_type: str,
    rating: RatingScale | None,
    value: str | tuple[str, ...],
    expected: SurveyAnswerKind,
) -> None:
    assert answer_kind(make_answer(question_type, value, rating)) == expected


def test_counts_thumbs_up_and_down_across_responses() -> None:
    responses = [
        make_response(make_answer("rating", "1", THUMBS), make_answer("open", "Fine."), minute=1),
        make_response(make_answer("rating", "2", THUMBS), minute=2),
        make_response(make_answer("rating", "1", THUMBS), minute=3),
    ]

    assert count_thumbs(responses) == ThumbsCount(up=2, down=1)


@parameterized.expand(
    [
        (
            "the hint's day, when feedback arrived days later",
            [make_feedback_row(uuid="m1", metric_value_json="1", timestamp=T0 + timedelta(days=4))],
            T0,
            datetime(2026, 9, 1, tzinfo=UTC),
        ),
        (
            "the earliest row's day, when the hint is later",
            [
                make_feedback_row(uuid="m1", metric_value_json="1", timestamp=T0 + timedelta(days=2)),
                make_feedback_row(uuid="e0", event="$ai_span", timestamp=T0 + timedelta(hours=13)),
            ],
            T0 + timedelta(days=3),
            datetime(2026, 9, 1, tzinfo=UTC),
        ),
        ("the hint's day without rows", [], T0 + timedelta(days=3), datetime(2026, 9, 4, tzinfo=UTC)),
        ("nothing without rows or a hint", [], None, None),
    ]
)
def test_survey_window_covers_the_trace_day_and_the_30_days_after_it(
    _name: str, rows: list[FeedbackEventRow], timestamp_hint: datetime | None, start: datetime | None
) -> None:
    window = survey_window(rows, timestamp_hint)

    assert window == (SurveyWindow(start=start, end=start + timedelta(days=31)) if start else None)
