from datetime import datetime
from uuid import uuid4

import pytz

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import Team
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.session_replay_event.sql import SELECT_ALL_SUMMARIZED_SESSIONS

from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries, ClickhouseDestroyTablesMixin
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
    mouse_activity_count
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    minState(toDateTime64(%(first_timestamp)s, 6, 'UTC')),
    maxState(toDateTime64(%(last_timestamp)s, 6, 'UTC')),
    anyState(%(first_url)s),
    %(click_count)s,
    %(keypress_count)s,
    %(mouse_activity_count)s
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
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, sql=INSERT_SINGLE_SESSION_REPLAY, data=data)


def make_filter(serializer_klass=AppMetricsRequestSerializer, **kwargs) -> AppMetricsRequestSerializer:
    filter = serializer_klass(data=kwargs)
    filter.is_valid(raise_exception=True)
    return filter


class SessionReplaySummaryQuery:
    def __init__(self, team: Team):
        self.team = team

    def run(self):
        results = sync_execute(
            SELECT_ALL_SUMMARIZED_SESSIONS,
            # {"team_id": self.team.pk, "from_date": format_clickhouse_timestamp(datetime.now() - timedelta(hours=24))},
        )
        return results


# TODO remove the ClickhouseDestroyTablesMixin once queries are being targeted by date/session_id
class TestReceiveSummarizedSessionReplays(ClickhouseDestroyTablesMixin, ClickhouseTestMixin, BaseTest):
    @snapshot_clickhouse_queries
    def test_something(self):
        session_id = str(uuid4())

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            # can CH handle a timestamp with no T
            first_timestamp="2023-04-27 14:20:40.309",
            last_timestamp="2023-04-27 14:20:42.237",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp="2023-04-26T19:17:38.116",
            last_timestamp="2023-04-26T19:17:38.117",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp="2023-04-26T19:18:24.597",
            last_timestamp="2023-04-26T19:20:24.597",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        results = SessionReplaySummaryQuery(self.team).run()
        assert results == [
            (
                session_id,
                self.team.pk,
                str(self.user.distinct_id),
                datetime(2023, 4, 26, 19, 17, 38, 116000, tzinfo=pytz.UTC),
                datetime(2023, 4, 27, 14, 20, 42, 237000, tzinfo=pytz.UTC),
                6,
                6,
                6,
            )
        ]
