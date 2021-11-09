from uuid import uuid4

from ee.clickhouse.models.action import Action, ActionStep
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.session_recordings.test.test_session_recording_list import factory_session_recordings_list_test


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessionRecordingsList(ClickhouseTestMixin, factory_session_recordings_list_test(ClickhouseSessionRecordingList, _create_event, _create_session_recording_event, Action.objects.create, ActionStep.objects.create)):  # type: ignore
    pass
