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


def test_event_removal_requires_events_or_delete_all_events():
    request = DataDeletionRequest(**_base_kwargs(events=[], delete_all_events=False))
    with pytest.raises(ValidationError, match="Provide at least one event"):
        request.clean()


def test_event_removal_rejects_events_with_delete_all_events():
    request = DataDeletionRequest(**_base_kwargs(events=["$pageview"], delete_all_events=True))
    with pytest.raises(ValidationError, match="Events must be empty"):
        request.clean()


def test_event_removal_passes_with_events_and_no_delete_all_events():
    request = DataDeletionRequest(**_base_kwargs(events=["$pageview"], delete_all_events=False))
    request.clean()  # should not raise


def test_event_removal_passes_with_delete_all_events_and_no_events():
    request = DataDeletionRequest(**_base_kwargs(events=[], delete_all_events=True))
    request.clean()  # should not raise


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
