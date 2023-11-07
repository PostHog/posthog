from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun.api import freeze_time

from posthog.models import Person
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.session_recordings.queries.session_recording_properties import (
    SessionRecordingProperties,
)
from posthog.session_recordings.queries.test.session_replay_sql import (
    produce_replay_summary,
)
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    snapshot_clickhouse_queries,
)


class TestSessionRecordingProperties(BaseTest, ClickhouseTestMixin):
    def create_event(
        self,
        distinct_id,
        timestamp,
        team=None,
        event_name="$pageview",
        properties={"$os": "Windows 95", "$current_url": "aloha.com/2"},
    ):
        if team is None:
            team = self.team
        _create_event(
            team=team,
            event=event_name,
            timestamp=timestamp,
            distinct_id=distinct_id,
            properties=properties,
        )

    @property
    def base_time(self):
        return now() - relativedelta(hours=1)

    @freeze_time("2021-01-21T20:00:00.000Z")
    @snapshot_clickhouse_queries
    def test_properties_list(self):
        Person.objects.create(team=self.team, distinct_ids=["user"], properties={"email": "bla"})
        produce_replay_summary(
            team_id=self.team.id,
            session_id="1",
            distinct_id="user",
            first_timestamp=self.base_time,
            last_timestamp=self.base_time,
        )
        produce_replay_summary(
            team_id=self.team.id,
            session_id="2",
            distinct_id="user",
            first_timestamp=self.base_time,
            last_timestamp=self.base_time,
        )

        event_props = {
            "$session_id": "1",
            "$window_id": "1",
            "should_not_be_included": "1",
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "$device_type": "Desktop",
            "$current_url": "https://blah.com/blah",
            "$host": "blah.com",
            "$pathname": "/blah",
            "$geoip_country_code": "KR",
        }
        self.create_event(
            "user",
            self.base_time,
            properties=event_props,
        )
        self.create_event(
            "user",
            self.base_time,
            properties=event_props,
        )

        filter = SessionRecordingsFilter(team=self.team, data={"no_filter": None})
        session_recording_properties_instance = SessionRecordingProperties(
            filter=filter, team=self.team, session_ids=["1"]
        )
        session_recordings_properties = session_recording_properties_instance.run()
        self.assertEqual(len(session_recordings_properties), 1)
        self.assertEqual(session_recordings_properties[0]["properties"]["$browser"], "Chrome")
        self.assertEqual(session_recordings_properties[0]["properties"]["$os"], "Mac OS X")
        self.assertEqual(session_recordings_properties[0]["properties"]["$device_type"], "Desktop")
        self.assertEqual(
            session_recordings_properties[0]["properties"]["$current_url"],
            "https://blah.com/blah",
        )
        self.assertEqual(session_recordings_properties[0]["properties"]["$host"], "blah.com")
        self.assertEqual(session_recordings_properties[0]["properties"]["$pathname"], "/blah")
        self.assertEqual(session_recordings_properties[0]["properties"]["$geoip_country_code"], "KR")
        self.assertNotIn("should_not_be_included", session_recordings_properties[0]["properties"])
