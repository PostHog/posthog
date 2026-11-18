from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.events_fallback import FALLBACK_AFTER_HINT, page_window
from products.ai_observability.backend.logic.traces.sentiment_queries import (
    MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE,
    TraceSentimentRow,
    load_sentiments,
)

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
WINDOW = page_window((T0, T0))
WITHIN_RETENTION = T0 + timedelta(days=1)
PAST_RETENTION = T0 + timedelta(days=60)


def _sentiment(label: str, score: float, generation_id: str) -> dict[str, object]:
    return {
        "$ai_evaluation_runtime": "sentiment",
        "$ai_target_event_id": generation_id,
        "$ai_sentiment_label": label,
        "$ai_sentiment_score": score,
        "$ai_sentiment_scores": {
            "positive": score if label == "positive" else 0.1,
            "neutral": 0.1,
            "negative": score if label == "negative" else 0.1,
        },
        "$ai_sentiment_message_count": 1,
    }


def _event(
    team: Team, trace_id: str, properties: dict[str, object], timestamp: datetime, index: int
) -> dict[str, object]:
    return {
        "event": "$ai_evaluation",
        "event_uuid": f"00000000-0000-4000-8000-{index:012d}",
        "distinct_id": "user-1",
        "team": team,
        "timestamp": timestamp,
        "properties": {"$ai_trace_id": trace_id, **properties},
    }


class TestSentimentQueries(ClickhouseTestMixin, BaseTest):
    def test_each_generation_counts_its_latest_result_from_this_team_only(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        bulk_create_ai_events(
            [
                _event(self.team, "rated", _sentiment("positive", 0.9, "generation-1"), T0, 0),
                _event(self.team, "rated", _sentiment("negative", 0.8, "generation-1"), T0 + timedelta(minutes=1), 1),
                _event(other_team, "unrated", _sentiment("negative", 0.8, "generation-2"), T0, 2),
            ]
        )

        sentiments = load_sentiments(self.team, self.user, ["rated", "unrated"], WINDOW, WITHIN_RETENTION)

        assert sentiments == {"rated": TraceSentimentRow(label="negative", score=0.8)}

    def test_a_trace_with_more_rated_generations_than_the_cap_leaves_room_for_the_others(self) -> None:
        bulk_create_ai_events(
            [
                _event(self.team, "quiet", _sentiment("negative", 0.8, "generation-quiet"), T0, 0),
                *(
                    _event(
                        self.team,
                        "busy",
                        _sentiment("positive", 0.9, f"generation-{index}"),
                        T0 + timedelta(seconds=index),
                        index,
                    )
                    # Enough newer results to fill the whole two-trace page if the cap were page-wide.
                    for index in range(1, 2 * MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE + 1)
                ),
            ]
        )

        sentiments = load_sentiments(self.team, self.user, ["busy", "quiet"], WINDOW, WITHIN_RETENTION)

        assert sentiments == {
            "busy": TraceSentimentRow(label="positive", score=0.9),
            "quiet": TraceSentimentRow(label="negative", score=0.8),
        }

    def test_a_page_within_retention_reads_only_ai_events(self) -> None:
        bulk_create_events([_event(self.team, "aged", _sentiment("negative", 0.8, "generation-1"), T0, 0)])

        with self.capture_select_queries() as queries:
            sentiments = load_sentiments(self.team, self.user, ["aged", "unrated"], WINDOW, WITHIN_RETENTION)

        assert sentiments == {}
        assert len(queries) == 1

    def test_a_page_past_retention_reads_the_shared_table_from_the_window_start_until_now(self) -> None:
        bulk_create_events(
            [
                _event(self.team, "inside", _sentiment("negative", 0.8, "generation-1"), T0, 0),
                _event(
                    self.team,
                    "rated-later",
                    _sentiment("negative", 0.8, "generation-2"),
                    T0 + FALLBACK_AFTER_HINT + timedelta(hours=1),
                    1,
                ),
                _event(
                    self.team,
                    "before",
                    _sentiment("negative", 0.8, "generation-3"),
                    WINDOW.start - timedelta(minutes=1),
                    2,
                ),
                _event(
                    self.team,
                    "future",
                    _sentiment("negative", 0.8, "generation-4"),
                    PAST_RETENTION + timedelta(hours=1),
                    3,
                ),
            ]
        )

        sentiments = load_sentiments(
            self.team, self.user, ["inside", "rated-later", "before", "future"], WINDOW, PAST_RETENTION
        )

        assert sentiments == {
            "inside": TraceSentimentRow(label="negative", score=0.8),
            "rated-later": TraceSentimentRow(label="negative", score=0.8),
        }
