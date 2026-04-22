from datetime import datetime, timedelta

import pytest

from django.core.exceptions import ValidationError

from posthog.models.data_deletion_request import DataDeletionRequest, RequestType

TEAM_ID = 99999


def _base_kwargs(**overrides) -> dict:
    kwargs = {
        "team_id": TEAM_ID,
        "request_type": RequestType.EVENT_REMOVAL,
        "start_time": datetime.now() - timedelta(days=7),
        "end_time": datetime.now(),
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.parametrize(
    "events,delete_all_events,match",
    [
        ([], False, "Provide at least one event"),
        (["$pageview"], True, "Events must be empty"),
    ],
)
def test_event_removal_clean_raises(events, delete_all_events, match):
    request = DataDeletionRequest(**_base_kwargs(events=events, delete_all_events=delete_all_events))
    with pytest.raises(ValidationError, match=match):
        request.clean()


@pytest.mark.parametrize(
    "events,delete_all_events",
    [
        (["$pageview"], False),
        ([], True),
    ],
)
def test_event_removal_clean_passes(events, delete_all_events):
    request = DataDeletionRequest(**_base_kwargs(events=events, delete_all_events=delete_all_events))
    request.clean()


def test_non_event_removal_cannot_set_delete_all_events():
    request = DataDeletionRequest(
        **_base_kwargs(
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=["$ip"],
            delete_all_events=True,
        )
    )
    with pytest.raises(ValidationError, match="only valid for event_removal"):
        request.clean()
