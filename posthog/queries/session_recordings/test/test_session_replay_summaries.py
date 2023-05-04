from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4
from dateutil.parser import isoparse
import pytz

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import Team
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.session_replay_event.sql import SELECT_SUMMARIZED_SESSIONS

from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.utils import cast_timestamp_or_now

INSERT_SINGLE_SESSION_REPLAY = """
INSERT INTO sharded_session_replay_events (
        session_id,
    team_id,
    distinct_id,
    first_timestamp,
    last_timestamp,
    first_url,
    click_count,
    keypress_count,
    mouse_activity_count,
    active_milliseconds
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    min(toDateTime64(%(first_timestamp)s, 6, 'UTC')),
    max(toDateTime64(%(last_timestamp)s, 6, 'UTC')),
    anyState(%(first_url)s),
    %(click_count)s,
    %(keypress_count)s,
    %(mouse_activity_count)s,
    %(active_milliseconds)s
"""


def produce_replay_summary(
    session_id: str,
    team_id: int,
    distinct_id: str,
    first_timestamp: str,
    last_timestamp: str,
    first_url: str | None,
    click_count: int,
    keypress_count: int,
    mouse_activity_count: int,
    active_milliseconds: Optional[float] = None,
):

    data = {
        "session_id": session_id,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "first_timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(first_timestamp)),
        "last_timestamp": format_clickhouse_timestamp(cast_timestamp_or_now(last_timestamp)),
        "first_url": first_url,
        "click_count": click_count,
        "keypress_count": keypress_count,
        "mouse_activity_count": mouse_activity_count,
        "active_milliseconds": active_milliseconds or 0,
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, sql=INSERT_SINGLE_SESSION_REPLAY, data=data)


def make_filter(serializer_klass=AppMetricsRequestSerializer, **kwargs) -> AppMetricsRequestSerializer:
    filter = serializer_klass(data=kwargs)
    filter.is_valid(raise_exception=True)
    return filter


class SessionReplaySummaryQuery:
    def __init__(self, team: Team, session_id: str, reference_date: str):
        self.team = team
        self.session_id = session_id
        self.reference_date = reference_date

    def list_all(self):
        params = {
            "team_id": self.team.pk,
            "start_time": format_clickhouse_timestamp(isoparse(self.reference_date) - timedelta(hours=48)),
            "end_time": format_clickhouse_timestamp(isoparse(self.reference_date) + timedelta(hours=48)),
            "session_ids": (self.session_id,),
        }

        results = sync_execute(
            SELECT_SUMMARIZED_SESSIONS,
            params,
        )
        return results


class TestReceiveSummarizedSessionReplays(ClickhouseTestMixin, BaseTest):
    @snapshot_clickhouse_queries
    def test_session_replay_summaries_can_be_queried(self):
        session_id = str(uuid4())

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp="2023-04-27 10:00:00.309",
            last_timestamp="2023-04-27 14:20:42.237",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=33624 * 1000 * 0.3,  # 30% of the total expected duration
        )

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp="2023-04-27T19:17:38.116",
            last_timestamp="2023-04-27T19:17:38.117",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp="2023-04-27T19:18:24.597",
            last_timestamp="2023-04-27T19:20:24.597",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        # same session but starts more than 2 days ago so excluded
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp="2023-04-22T19:18:24.597",
            last_timestamp="2023-04-26T19:20:24.597",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        # same session but ends more than 2 days from start so excluded
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp="2023-04-26T19:18:24.597",
            last_timestamp="2023-04-29T19:20:24.597",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        # same session but a different team so excluded
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk + 100,
            first_timestamp="2023-04-26T19:18:24.597",
            last_timestamp="2023-04-28T19:20:24.597",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        # different session so excluded
        produce_replay_summary(
            session_id=str(uuid4()),
            team_id=self.team.pk,
            first_timestamp="2023-04-26T19:18:24.597",
            last_timestamp="2023-04-26T19:20:24.597",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        results = SessionReplaySummaryQuery(self.team, session_id, "2023-04-26T19:18:24.597").list_all()
        assert results == [
            (
                session_id,
                self.team.pk,
                str(self.user.distinct_id),
                datetime(2023, 4, 27, 10, 0, 0, 309000, tzinfo=pytz.UTC),
                datetime(2023, 4, 27, 19, 20, 24, 597000, tzinfo=pytz.UTC),
                33624,
                6,
                6,
                6,
                0.3,
            )
        ]
