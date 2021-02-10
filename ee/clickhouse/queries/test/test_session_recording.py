from uuid import uuid4

from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.clickhouse_session_recording import SessionRecording, filter_sessions_by_recordings
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.sessions.test.test_session_recording import session_recording_test_factory


def _create_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessionRecording(
    ClickhouseTestMixin, session_recording_test_factory(SessionRecording, filter_sessions_by_recordings, _create_event)  # type: ignore
):
    pass
