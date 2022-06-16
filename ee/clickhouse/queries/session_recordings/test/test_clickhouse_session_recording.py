from uuid import uuid4

from posthog.models.session_recording_event.util import create_session_recording_event
from posthog.queries.session_recordings.session_recording import SessionRecording
from posthog.queries.session_recordings.test.test_session_recording import factory_session_recording_test
from posthog.test.base import ClickhouseTestMixin


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessionRecording(ClickhouseTestMixin, factory_session_recording_test(SessionRecording, _create_session_recording_event)):  # type: ignore
    pass
