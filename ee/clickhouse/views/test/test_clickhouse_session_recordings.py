from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone

from ee.clickhouse.models.session_recording_event import create_session_recording_event
from posthog.api.test.test_session_recordings import factory_test_session_recordings_api


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class ClickhouseTestSessionRecordingsAPI(factory_test_session_recordings_api(_create_session_recording_event)):
    pass
