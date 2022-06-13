from uuid import uuid4

from ee.clickhouse.models.session_recording_event import create_session_recording_event
from posthog.api.test.test_session_recordings import factory_test_session_recordings_api
from posthog.test.base import ClickhouseTestMixin


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class ClickhouseTestSessionRecordingsAPI(ClickhouseTestMixin, factory_test_session_recordings_api(_create_session_recording_event)):  # type: ignore
    pass
