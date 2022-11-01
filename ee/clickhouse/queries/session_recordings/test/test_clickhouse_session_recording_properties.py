from posthog.queries.session_recordings.session_recording_properties import SessionRecordingProperties
from posthog.queries.session_recordings.test.test_session_recording_properties import (
    factory_session_recordings_properties_test,
)
from posthog.test.base import ClickhouseTestMixin, _create_event


class TestClickhouseSessionRecordingsList(
    ClickhouseTestMixin,
    factory_session_recordings_properties_test(SessionRecordingProperties, _create_event),  # type: ignore
):
    pass
