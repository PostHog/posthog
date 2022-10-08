from posthog.api.test.test_session_recordings import factory_test_session_recordings_api
from posthog.test.base import ClickhouseTestMixin, _create_session_recording_event


class ClickhouseTestSessionRecordingsAPI(ClickhouseTestMixin, factory_test_session_recordings_api(_create_session_recording_event)):  # type: ignore
    pass
