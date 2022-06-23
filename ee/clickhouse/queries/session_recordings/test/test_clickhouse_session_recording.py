from posthog.queries.session_recordings.session_recording import SessionRecording
from posthog.queries.session_recordings.test.test_session_recording import factory_session_recording_test
from posthog.test.base import ClickhouseTestMixin


class TestClickhouseSessionRecording(ClickhouseTestMixin, factory_session_recording_test(SessionRecording)):  # type: ignore
    pass
