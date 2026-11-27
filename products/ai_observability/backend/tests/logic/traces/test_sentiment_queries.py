import json
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, patch_clickhouse_client_execute

from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.events_fallback import (
    AI_EVENTS_RETENTION_DAYS,
    FALLBACK_AFTER_HINT,
    FallbackWindow,
    page_window,
)
from products.ai_observability.backend.logic.traces.sentiment_queries import (
    MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE,
    SENTIMENT_QUERY_NAME,
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

        returned_rows: list[int] = []

        def record_rows(execute: Any, query: str, *args: Any, **kwargs: Any) -> Any:
            result = execute(query, *args, **kwargs)
            tags = json.loads((kwargs.get("settings") or {}).get("log_comment", "{}"))
            if tags.get("name") == SENTIMENT_QUERY_NAME:
                returned_rows.append(len(result[0] if kwargs.get("with_column_types") else result))
            return result

        with patch_clickhouse_client_execute(record_rows):
            sentiments = load_sentiments(self.team, self.user, ["busy", "quiet"], WINDOW, WITHIN_RETENTION)

        assert sentiments == {
            "busy": TraceSentimentRow(label="positive", score=0.9),
            "quiet": TraceSentimentRow(label="negative", score=0.8),
        }
        assert returned_rows == [2]

    def test_newer_results_that_counted_no_messages_leave_room_for_an_older_one(self) -> None:
        bulk_create_ai_events(
            [
                _event(self.team, "busy", _sentiment("negative", 0.8, "generation-rated"), T0, 0),
                *(
                    _event(
                        self.team,
                        "busy",
                        {**_sentiment("positive", 0.9, f"generation-{index}"), "$ai_sentiment_message_count": 0},
                        T0 + timedelta(seconds=index),
                        index,
                    )
                    for index in range(1, MAX_GENERATION_SENTIMENT_EVALUATIONS_PER_TRACE + 1)
                ),
            ]
        )

        sentiments = load_sentiments(self.team, self.user, ["busy"], WINDOW, WITHIN_RETENTION)

        assert sentiments == {"busy": TraceSentimentRow(label="negative", score=0.8)}

    def test_a_page_within_retention_reads_only_ai_events(self) -> None:
        bulk_create_events([_event(self.team, "aged", _sentiment("negative", 0.8, "generation-1"), T0, 0)])

        with self.capture_select_queries() as queries:
            sentiments = load_sentiments(self.team, self.user, ["aged", "unrated"], WINDOW, WITHIN_RETENTION)

        assert sentiments == {}
        assert len(queries) == 1

    def test_a_page_ending_at_the_last_datetime_reads_the_shared_table_without_overflowing(self) -> None:
        window = FallbackWindow(start=WINDOW.start, end=datetime(9999, 12, 31, tzinfo=UTC))
        bulk_create_events([_event(self.team, "aged", _sentiment("negative", 0.8, "generation-1"), T0, 0)])

        sentiments = load_sentiments(self.team, self.user, ["aged"], window, PAST_RETENTION)

        assert sentiments == {"aged": TraceSentimentRow(label="negative", score=0.8)}

    def test_a_page_past_retention_reads_the_shared_table_until_its_generations_leave_ai_events(self) -> None:
        retention_end = WINDOW.end + timedelta(days=AI_EVENTS_RETENTION_DAYS + 1)
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
                    "rated-after-retention",
                    _sentiment("negative", 0.8, "generation-4"),
                    retention_end + timedelta(hours=1),
                    3,
                ),
            ]
        )

        sentiments = load_sentiments(
            self.team, self.user, ["inside", "rated-later", "before", "rated-after-retention"], WINDOW, PAST_RETENTION
        )

        assert sentiments == {
            "inside": TraceSentimentRow(label="negative", score=0.8),
            "rated-later": TraceSentimentRow(label="negative", score=0.8),
        }
