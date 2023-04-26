from datetime import datetime
from uuid import uuid4

import pytz
from freezegun.api import freeze_time

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import Team
from posthog.models.event.util import format_clickhouse_timestamp

from posthog.queries.app_metrics.serializers import AppMetricsRequestSerializer
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries, ClickhouseDestroyTablesMixin
from posthog.utils import cast_timestamp_or_now

INSERT_SINGLE_SESSION_REPLAY = """
INSERT INTO sharded_session_replay_events (
        session_id,
    team_id,
    distinct_id,
    timestamp,
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
    %(timestamp)s,
    minState(toDateTime64(%(timestamp)s, 6, 'UTC')),
    maxState(toDateTime64(%(timestamp)s, 6, 'UTC')),
    anyState(%(first_url)s),
    %(click_count)s,
    %(keypress_count)s,
    %(mouse_activity_count)s
"""


def produce_replay_summary(
    session_id: str,
    team_id: int,
    distinct_id: str,
    timestamp: str,
    first_url: str | None,
    click_count: int,
    keypress_count: int,
    mouse_activity_count: int,
):
    timestamp = cast_timestamp_or_now(timestamp)
    data = {
        "session_id": session_id,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "timestamp": format_clickhouse_timestamp(timestamp),
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
    QUERY = """
    select
           session_id,
           any(team_id),
           any(distinct_id),
           minMerge(first_timestamp),
           maxMerge(last_timestamp),
           sum(click_count),
           sum(keypress_count),
           sum(mouse_activity_count)
    from session_replay_events
    group by session_id
    """

    def __init__(self, team: Team):
        self.team = team

    def run(self):
        results = sync_execute(
            self.QUERY,
            # {"team_id": self.team.pk, "from_date": format_clickhouse_timestamp(datetime.now() - timedelta(hours=24))},
        )
        return results


# TODO remove the ClickhouseDestroyTablesMixin once queries are being targeted by date/session_id
class TestReceiveSummarizedSessionReplays(ClickhouseDestroyTablesMixin, ClickhouseTestMixin, BaseTest):
    @freeze_time("2021-12-05T13:23:00Z")
    @snapshot_clickhouse_queries
    def test_something(self):
        session_id = str(uuid4())
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            timestamp="2021-12-01T00:10:00",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            timestamp="2021-12-05T00:10:00",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            timestamp="2021-12-05T00:10:00",
            distinct_id=str(self.user.distinct_id),
            first_url=None,
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
        )
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            timestamp="2021-12-05T00:10:00",
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
                datetime(2021, 12, 1, 0, 10, tzinfo=pytz.UTC),
                datetime(2021, 12, 5, 0, 10, tzinfo=pytz.UTC),
                8,
                8,
                8,
            )
        ]


#     @freeze_time("2021-12-05T13:23:00Z")
#     def test_ignores_out_of_bound_metrics(self):
#         produce_replay_summary(
#             team_id=-1, category="processEvent", plugin_config_id=3, timestamp="2021-12-05T00:10:00Z", successes=5
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=1,
#             timestamp="2021-12-04T00:10:00Z",
#             failures=1,
#         )
#         results = TeamPluginsDeliveryRateQuery(self.team).run()
#         self.assertEqual(results, {})
#
#
# class TestAppMetricsQuery(ClickhouseTestMixin, BaseTest):
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_app_metrics(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-03T00:00:00Z",
#             successes=3,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-03T00:00:00Z",
#             failures=2,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T00:20:00Z",
#             successes=10,
#             successes_on_retry=5,
#         )
#         filter = make_filter(category="processEvent", date_from="-7d")
#
#         results = AppMetricsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results["dates"],
#             [
#                 "2021-11-28",
#                 "2021-11-29",
#                 "2021-11-30",
#                 "2021-12-01",
#                 "2021-12-02",
#                 "2021-12-03",
#                 "2021-12-04",
#                 "2021-12-05",
#             ],
#         )
#         self.assertEqual(results["successes"], [0, 0, 0, 0, 0, 3, 0, 10])
#         self.assertEqual(results["successes_on_retry"], [0, 0, 0, 0, 0, 0, 0, 5])
#         self.assertEqual(results["failures"], [1, 0, 0, 0, 0, 2, 0, 0])
#         self.assertEqual(results["totals"], {"successes": 13, "successes_on_retry": 5, "failures": 3})
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_filter_by_job_id(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="exportEvents",
#             plugin_config_id=3,
#             job_id="12345",
#             timestamp="2021-12-05T00:10:00Z",
#             successes_on_retry=2,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="exportEvents",
#             plugin_config_id=3,
#             job_id="67890",
#             timestamp="2021-12-05T00:20:00Z",
#             failures=1,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="exportEvents",
#             plugin_config_id=3,
#             timestamp="2021-12-05T00:10:00Z",
#             successes=3,
#         )
#         filter = make_filter(category="exportEvents", date_from="-7d", job_id="12345")
#
#         results = AppMetricsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(results["successes_on_retry"], [0, 0, 0, 0, 0, 0, 0, 2])
#         self.assertEqual(results["totals"], {"successes": 0, "successes_on_retry": 2, "failures": 0})
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_filter_by_hourly_date_range(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T00:10:00Z",
#             successes=2,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             job_id="67890",
#             timestamp="2021-12-05T01:20:00Z",
#             successes=1,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T02:10:00Z",
#             successes=3,
#         )
#         filter = make_filter(category="processEvent", date_from="-13h", date_to="-5h")
#
#         results = AppMetricsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results["dates"],
#             [
#                 "2021-12-05 00:00:00",
#                 "2021-12-05 01:00:00",
#                 "2021-12-05 02:00:00",
#                 "2021-12-05 03:00:00",
#                 "2021-12-05 04:00:00",
#                 "2021-12-05 05:00:00",
#                 "2021-12-05 06:00:00",
#                 "2021-12-05 07:00:00",
#                 "2021-12-05 08:00:00",
#             ],
#         )
#         self.assertEqual(results["successes"], [2, 1, 3, 0, 0, 0, 0, 0, 0])
#         self.assertEqual(results["totals"], {"successes": 6, "successes_on_retry": 0, "failures": 0})
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_ignores_unrelated_data(self):
#         # Positive examples: testing time bounds
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             successes=1,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             successes=2,
#         )
#
#         # Negative examples
#         # Different team
#         produce_replay_summary(
#             team_id=-1, category="processEvent", plugin_config_id=3, timestamp="2021-12-05T13:10:00Z", failures=1
#         )
#         # Different pluginConfigId
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=-1,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=2,
#         )
#         # Different category
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="exportEvents",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=3,
#         )
#         # Timestamp out of range
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-27T23:59:59Z",
#             failures=4,
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-06T00:00:00Z",
#             failures=5,
#         )
#
#         filter = make_filter(category="processEvent", date_from="-7d")
#
#         results = AppMetricsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(results["totals"], {"successes": 3, "successes_on_retry": 0, "failures": 0})
#
#
# class TestAppMetricsErrorsQuery(ClickhouseTestMixin, BaseTest):
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_errors_query(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="SomeError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-03T00:00:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-03T00:00:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T00:20:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#
#         filter = make_filter(category="processEvent", date_from="-7d")
#         results = AppMetricsErrorsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results,
#             [
#                 {
#                     "error_type": "AnotherError",
#                     "count": 3,
#                     "last_seen": datetime.fromisoformat("2021-12-05T00:20:00+00:00"),
#                 },
#                 {
#                     "error_type": "SomeError",
#                     "count": 1,
#                     "last_seen": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
#                 },
#             ],
#         )
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_errors_query_filter_by_job_id(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="SomeError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             job_id="1234",
#             timestamp="2021-12-03T00:00:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             job_id="1234",
#             timestamp="2021-12-03T00:00:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             job_id="5678",
#             timestamp="2021-12-05T00:20:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#
#         filter = make_filter(category="processEvent", date_from="-7d", job_id="1234")
#         results = AppMetricsErrorsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results,
#             [
#                 {
#                     "error_type": "AnotherError",
#                     "count": 2,
#                     "last_seen": datetime.fromisoformat("2021-12-03T00:00:00+00:00"),
#                 },
#             ],
#         )
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_ignores_unrelated_data(self):
#         # Positive examples: testing time bounds
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="RelevantError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="RelevantError",
#         )
#
#         # Negative examples
#         # Different team
#         produce_replay_summary(
#             team_id=-1,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         # Different pluginConfigId
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=-1,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         # Different category
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="exportEvents",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         # Timestamp out of range
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-27T23:59:59Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-06T00:00:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="AnotherError",
#         )
#
#         filter = make_filter(category="processEvent", date_from="-7d")
#         results = AppMetricsErrorsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results,
#             [
#                 {
#                     "error_type": "RelevantError",
#                     "count": 2,
#                     "last_seen": datetime.fromisoformat("2021-12-05T13:10:00+00:00"),
#                 },
#             ],
#         )
#
#
# class TestAppMetricsErrorDetailsQuery(ClickhouseTestMixin, BaseTest):
#     UUIDS = [UUIDT() for _ in range(2)]
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_error_details_query(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#             error_uuid=str(self.UUIDS[0]),
#             error_type="SomeError",
#             error_details={"event": {}},
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T00:10:00Z",
#             failures=1,
#             error_uuid=str(self.UUIDS[1]),
#             error_type="SomeError",
#             error_details={"event": {}},
#         )
#
#         filter = make_filter(
#             serializer_klass=AppMetricsErrorsRequestSerializer, category="processEvent", error_type="SomeError"
#         )
#         results = AppMetricsErrorDetailsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results,
#             [
#                 {
#                     "timestamp": datetime.fromisoformat("2021-12-05T00:10:00+00:00"),
#                     "error_uuid": self.UUIDS[1],
#                     "error_type": "SomeError",
#                     "error_details": {"event": {}},
#                 },
#                 {
#                     "timestamp": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
#                     "error_uuid": self.UUIDS[0],
#                     "error_type": "SomeError",
#                     "error_details": {"event": {}},
#                 },
#             ],
#         )
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_error_details_query_filter_by_job_id(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             job_id="1234",
#             failures=1,
#             error_uuid=str(self.UUIDS[0]),
#             error_type="SomeError",
#             error_details={"event": {}},
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:20:00Z",
#             job_id="5678",
#             failures=1,
#             error_uuid=str(self.UUIDS[0]),
#             error_type="SomeError",
#             error_details={"event": {}},
#         )
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:30:00Z",
#             failures=1,
#             error_uuid=str(self.UUIDS[0]),
#             error_type="SomeError",
#             error_details={"event": {}},
#         )
#
#         filter = make_filter(
#             serializer_klass=AppMetricsErrorsRequestSerializer,
#             category="processEvent",
#             error_type="SomeError",
#             job_id="1234",
#         )
#         results = AppMetricsErrorDetailsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results,
#             [
#                 {
#                     "timestamp": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
#                     "error_uuid": self.UUIDS[0],
#                     "error_type": "SomeError",
#                     "error_details": {"event": {}},
#                 }
#             ],
#         )
#
#     @freeze_time("2021-12-05T13:23:00Z")
#     @snapshot_clickhouse_queries
#     def test_ignores_unrelated_data(self):
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#             error_uuid=str(self.UUIDS[0]),
#             error_type="SomeError",
#             error_details={"event": {}},
#         )
#
#         # Different team
#         produce_replay_summary(
#             team_id=-1,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="SomeError",
#         )
#         # Different pluginConfigId
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=-1,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="SomeError",
#         )
#         # Different category
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="exportEvents",
#             plugin_config_id=3,
#             timestamp="2021-12-05T13:10:00Z",
#             failures=1,
#             error_uuid=str(UUIDT()),
#             error_type="SomeError",
#         )
#         # Different error_type
#         produce_replay_summary(
#             team_id=self.team.pk,
#             category="processEvent",
#             plugin_config_id=3,
#             timestamp="2021-11-28T00:10:00Z",
#             failures=1,
#             error_uuid=str(self.UUIDS[0]),
#             error_type="AnotherError",
#             error_details={"event": {}},
#         )
#
#         filter = make_filter(
#             serializer_klass=AppMetricsErrorsRequestSerializer, category="processEvent", error_type="SomeError"
#         )
#         results = AppMetricsErrorDetailsQuery(self.team, 3, filter).run()
#
#         self.assertEqual(
#             results,
#             [
#                 {
#                     "timestamp": datetime.fromisoformat("2021-11-28T00:10:00+00:00"),
#                     "error_uuid": self.UUIDS[0],
#                     "error_type": "SomeError",
#                     "error_details": {"event": {}},
#                 }
#             ],
#         )
