from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


# def _create_action(**kwargs):
#     team = kwargs.pop("team")
#     name = kwargs.pop("name")
#     action = Action.objects.create(team=team, name=name)
#     ActionStep.objects.create(action=action, event=name)
#     return action


# def _create_person(**kwargs):
#     person = Person.objects.create(**kwargs)
#     return person


from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.session_recordings.session_recording_list import ClickhouseSessionRecordingList
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.queries.session_recordings.test.test_session_recording_list import factory_session_recordings_list_test


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestClickhouseSessionRecordingsList(ClickhouseTestMixin, factory_session_recordings_list_test(ClickhouseSessionRecordingList, _create_event, _create_session_recording_event)):  # type: ignore
    pass
