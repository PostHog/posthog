from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from posthog.dataclasses import frozen

from products.surveys.backend.facade.api import LinkedSurveyAnswer, LinkedSurveyResponse

from .trace_queries import FeedbackEventRow

SurveyAnswerKind = Literal["thumbs", "rating", "choice", "text"]

# Surveys stores a 2-point rating as "1" for thumbs up and "2" for thumbs down, whatever its display.
THUMBS_UP = "1"
THUMBS_DOWN = "2"

# Users answer a survey about a trace some time after it ran, so the read looks past the trace's own day.
SURVEY_DAYS_AFTER_TRACE = 30


@frozen
class SurveyWindow:
    start: datetime
    end: datetime


@frozen
class ThumbsCount:
    up: int
    down: int


def survey_window(rows: Sequence[FeedbackEventRow], timestamp_hint: datetime | None) -> SurveyWindow | None:
    """The trace's UTC day and the `SURVEY_DAYS_AFTER_TRACE` days after it. The trace's day is the earliest of the hint
    and the feedback rows. None when neither says when the trace ran."""
    known = [moment for moment in (timestamp_hint, *(row.timestamp for row in rows)) if moment is not None]
    if not known:
        return None
    start = datetime.combine(min(known).astimezone(UTC).date(), time(), tzinfo=UTC)
    return SurveyWindow(start=start, end=start + timedelta(days=1 + SURVEY_DAYS_AFTER_TRACE))


def answer_kind(answer: LinkedSurveyAnswer) -> SurveyAnswerKind:
    if answer.question_type == "rating":
        is_thumbs = answer.rating is not None and answer.rating.scale == 2 and answer.value in (THUMBS_UP, THUMBS_DOWN)
        return "thumbs" if is_thumbs else "rating"
    if answer.question_type in ("single_choice", "multiple_choice"):
        return "choice"
    return "text"


def count_thumbs(responses: Sequence[LinkedSurveyResponse]) -> ThumbsCount:
    thumbs = [answer.value for response in responses for answer in response.answers if answer_kind(answer) == "thumbs"]
    return ThumbsCount(up=thumbs.count(THUMBS_UP), down=thumbs.count(THUMBS_DOWN))
