from uuid import UUID
from posthog.hogql_queries.sessions_timeline_query_runner import SessionsTimelineQueryRunner
from posthog.schema import EventType, SessionsTimelineQuery, TimelineEntry
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for


class TestSessionsTimelineQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_runner(self, query: SessionsTimelineQuery) -> SessionsTimelineQueryRunner:
        return SessionsTimelineQueryRunner(team=self.team, query=query)

    @snapshot_clickhouse_queries
    def test_formal_sessions_global(self):
        journeys_for(
            team=self.team,
            events_by_person={
                (UUID("018b4ca4-45af-0000-0cf4-4504ae523461"), "person1"): [
                    # The sessions are sorted most recently started to least,
                    # while events within most recent to least recent
                    {
                        "event_uuid": "6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 12:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "c15119f2-b243-4547-ab46-1b29a0435948",
                        "event": "user signed up",
                        "timestamp": "2021-01-01 13:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "b826a13e-aae3-4766-b407-0d3a582140e4",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 14:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 17:00:00",
                        "properties": {"$session_id": "s2"},
                    },
                ],
                (UUID("018b4c9f-50c1-0000-d15c-073bd4789c0e"), "person2"): [  # Partly overlapping with person1
                    {
                        "event_uuid": "605f6843-bf83-4d7b-b9a0-4d6f7f57415f",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 13:30:00",
                        "properties": {"$session_id": "s3"},
                    },
                    {
                        "event_uuid": "04dde300-a6c3-4372-9366-80472c2d02b1",
                        "event": "did important thing",
                        "timestamp": "2021-01-02 02:00:00",
                        "properties": {"$session_id": "s3"},
                    },
                ],
            },
        )

        runner = self._create_runner(SessionsTimelineQuery(before="2021-01-01T18:00:00Z", after="2021-01-01T06:00:00Z"))
        response = runner.calculate()

        assert response.results == [
            TimelineEntry(
                sessionId="s2",
                events=[
                    EventType(
                        id="e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T17:00:00+00:00",
                        properties={"$session_id": "s2"},
                        elements=[],
                    )
                ],
                recording_duration_s=None,
            ),
            TimelineEntry(
                sessionId="s3",
                events=[
                    EventType(
                        id="04dde300-a6c3-4372-9366-80472c2d02b1",
                        distinct_id="person2",
                        event="did important thing",
                        timestamp="2021-01-02T02:00:00+00:00",
                        properties={"$session_id": "s3"},
                        elements=[],
                    ),
                    EventType(
                        id="605f6843-bf83-4d7b-b9a0-4d6f7f57415f",
                        distinct_id="person2",
                        event="$pageview",
                        timestamp="2021-01-01T13:30:00+00:00",
                        properties={"$session_id": "s3"},
                        elements=[],
                    ),
                ],
                recording_duration_s=None,
            ),
            TimelineEntry(
                sessionId="s1",
                events=[
                    EventType(
                        id="b826a13e-aae3-4766-b407-0d3a582140e4",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T14:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                    EventType(
                        id="c15119f2-b243-4547-ab46-1b29a0435948",
                        distinct_id="person1",
                        event="user signed up",
                        timestamp="2021-01-01T13:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                    EventType(
                        id="6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T12:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                ],
                recording_duration_s=None,
            ),
        ]

    @snapshot_clickhouse_queries
    def test_formal_sessions_for_person(self):
        persons = journeys_for(
            team=self.team,
            events_by_person={
                (UUID("018b4ca4-45af-0000-0cf4-4504ae523461"), "person1"): [
                    # The sessions are sorted most recently started to least,
                    # while events within most recent to least recent
                    {
                        "event_uuid": "6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 12:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "c15119f2-b243-4547-ab46-1b29a0435948",
                        "event": "user signed up",
                        "timestamp": "2021-01-01 13:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "b826a13e-aae3-4766-b407-0d3a582140e4",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 14:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 17:00:00",
                        "properties": {"$session_id": "s2"},
                    },
                ],
                (UUID("018b4c9f-50c1-0000-d15c-073bd4789c0e"), "person2"): [  # Partly overlapping with person1
                    {
                        "event_uuid": "605f6843-bf83-4d7b-b9a0-4d6f7f57415f",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 13:30:00",
                        "properties": {"$session_id": "s3"},
                    },
                    {
                        "event_uuid": "04dde300-a6c3-4372-9366-80472c2d02b1",
                        "event": "did important thing",
                        "timestamp": "2021-01-02 02:00:00",
                        "properties": {"$session_id": "s3"},
                    },
                ],
            },
        )
        person_1_uuid = str(persons["person1"].uuid)

        runner = self._create_runner(
            SessionsTimelineQuery(before="2021-01-01T18:00:00Z", after="2021-01-01T06:00:00Z", personId=person_1_uuid)
        )
        response = runner.calculate()

        assert response.results == [
            TimelineEntry(
                sessionId="s2",
                events=[
                    EventType(
                        id="e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T17:00:00+00:00",
                        properties={"$session_id": "s2"},
                        elements=[],
                    )
                ],
                recording_duration_s=None,
            ),
            TimelineEntry(
                sessionId="s1",
                events=[
                    EventType(
                        id="b826a13e-aae3-4766-b407-0d3a582140e4",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T14:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                    EventType(
                        id="c15119f2-b243-4547-ab46-1b29a0435948",
                        distinct_id="person1",
                        event="user signed up",
                        timestamp="2021-01-01T13:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                    EventType(
                        id="6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T12:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                ],
                recording_duration_s=None,
            ),
        ]

    @snapshot_clickhouse_queries
    def test_formal_and_informal_sessions_global(self):
        journeys_for(
            team=self.team,
            events_by_person={
                (UUID("018b4ca4-45af-0000-0cf4-4504ae523461"), "person1"): [
                    {
                        "event_uuid": "6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 12:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "c15119f2-b243-4547-ab46-1b29a0435948",
                        "event": "user signed up",
                        "timestamp": "2021-01-01 13:00:00",
                        "properties": {},  # No session ID
                    },
                    {
                        "event_uuid": "b826a13e-aae3-4766-b407-0d3a582140e4",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 13:10:00",
                        "properties": {},  # No session ID - this should be in the same entry as the previous event
                    },
                    {
                        "event_uuid": "fa16ea8a-3fb9-4cb3-9ce6-de25b21e3016",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 13:50:00",
                        "properties": {},  # No session ID - this should be in a new entry because of 40-minute gap
                    },
                    {
                        "event_uuid": "e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 17:00:00",
                        "properties": {"$session_id": "s2"},
                    },
                    {
                        "event_uuid": "fa16ea8a-3fb9-4cb3-9ce6-de25b21e3016",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 18:00:00",
                        "properties": {},  # No session ID - this should be in a single-event entry
                    },
                ],
                (UUID("018b4c9f-50c1-0000-d15c-073bd4789c0e"), "person2"): [
                    {
                        "event_uuid": "605f6843-bf83-4d7b-b9a0-4d6f7f57415f",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 13:30:00",
                        "properties": {"$session_id": "s3"},
                    },
                    {
                        "event_uuid": "04dde300-a6c3-4372-9366-80472c2d02b1",
                        "event": "did important thing",
                        "timestamp": "2021-01-01 19:00:00",
                        "properties": {},  # No session ID - this should be in a single-event entry
                    },
                ],
            },
        )

    @snapshot_clickhouse_queries
    def test_formal_session_with_recording(self):
        journeys_for(
            team=self.team,
            events_by_person={
                (UUID("018b4ca4-45af-0000-0cf4-4504ae523461"), "person1"): [
                    {
                        "event_uuid": "6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 12:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "c15119f2-b243-4547-ab46-1b29a0435948",
                        "event": "user signed up",
                        "timestamp": "2021-01-01 13:00:00",
                        "properties": {"$session_id": "s1"},
                    },
                    {
                        "event_uuid": "e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        "event": "$pageview",
                        "timestamp": "2021-01-01 17:00:00",
                        "properties": {"$session_id": "s2"},
                    },
                ],
            },
        )
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1",
            distinct_id="person1",
            first_timestamp="2021-01-01 12:30:00",
            last_timestamp="2021-01-01 12:39:00",
        )

        runner = self._create_runner(SessionsTimelineQuery(before="2021-01-01T18:00:00Z", after="2021-01-01T06:00:00Z"))
        response = runner.calculate()

        assert response.results == [
            TimelineEntry(
                sessionId="s2",
                events=[
                    EventType(
                        id="e1208e6b-8101-4dde-ba21-c47781bb5bad",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T17:00:00+00:00",
                        properties={"$session_id": "s2"},
                        elements=[],
                    )
                ],
                recording_duration_s=None,  # No recording
            ),
            TimelineEntry(
                sessionId="s1",
                events=[
                    EventType(
                        id="c15119f2-b243-4547-ab46-1b29a0435948",
                        distinct_id="person1",
                        event="user signed up",
                        timestamp="2021-01-01T13:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                    EventType(
                        id="6e6e645b-2936-4613-b409-b33f4d9a0f18",
                        distinct_id="person1",
                        event="$pageview",
                        timestamp="2021-01-01T12:00:00+00:00",
                        properties={"$session_id": "s1"},
                        elements=[],
                    ),
                ],
                recording_duration_s=540,
            ),
        ]

        # TODO
        # runner = self._create_runner(SessionsTimelineQuery(before="2021-01-01T18:00:00Z", after="2021-01-01T06:00:00Z"))
        # response = runner.calculate()

        # Here we have 4 sessions without an ID
        # assert response.results == [
        # ]
