from datetime import datetime, timedelta
from functools import partial
from uuid import uuid4

import pytest

from clickhouse_driver import Client
from dagster import build_op_context

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.data_deletion_requests import (
    DataDeletionRequestConfig,
    data_deletion_request_event_removal,
    execute_event_deletion,
    load_deletion_request,
    mark_deletion_complete,
)
from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType

TEAM_ID = 99999


def _insert_events(events: list[tuple], client: Client) -> None:
    client.execute(
        "INSERT INTO writable_events (team_id, event, uuid, timestamp) VALUES",
        events,
    )


def _count_events(team_id: int, client: Client) -> int:
    result = client.execute(
        "SELECT count() FROM writable_events WHERE team_id = %(team_id)s",
        {"team_id": team_id},
    )
    return result[0][0]


def _count_events_by_name(team_id: int, event_name: str, client: Client) -> int:
    result = client.execute(
        "SELECT count() FROM writable_events WHERE team_id = %(team_id)s AND event = %(event)s",
        {"team_id": team_id, "event": event_name},
    )
    return result[0][0]


@pytest.mark.django_db
def test_load_deletion_request_transitions_to_in_progress():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )

    config = DataDeletionRequestConfig(request_id=str(request.pk))
    context = build_op_context()
    result = load_deletion_request(context, config)

    assert result.team_id == TEAM_ID
    assert result.events == ["$pageview"]

    request.refresh_from_db()
    assert request.status == RequestStatus.IN_PROGRESS


@pytest.mark.django_db
def test_load_deletion_request_rejects_non_approved():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.DRAFT,
    )

    config = DataDeletionRequestConfig(request_id=str(request.pk))
    context = build_op_context()

    with pytest.raises(Exception, match="not an approved event_removal request"):
        load_deletion_request(context, config)

    request.refresh_from_db()
    assert request.status == RequestStatus.DRAFT


@pytest.mark.django_db
def test_load_deletion_request_rejects_property_removal():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["$pageview"],
        properties=["$ip"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )

    config = DataDeletionRequestConfig(request_id=str(request.pk))
    context = build_op_context()

    with pytest.raises(Exception, match="not an approved event_removal request"):
        load_deletion_request(context, config)


@pytest.mark.django_db
def test_mark_deletion_complete_transitions_status():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.IN_PROGRESS,
    )

    from posthog.dags.data_deletion_requests import DeletionRequestContext

    deletion_ctx = DeletionRequestContext(
        request_id=str(request.pk),
        team_id=TEAM_ID,
        start_time=request.start_time,
        end_time=request.end_time,
        events=["$pageview"],
    )
    context = build_op_context()
    mark_deletion_complete(context, deletion_ctx)

    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED


@pytest.mark.django_db
def test_execute_event_deletion_deletes_matching_events(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)  # exclusive upper bound, so push past the latest event

    matching_events = [(TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i)) for i in range(50)]
    other_event_name = [(TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i)) for i in range(30)]
    other_team = [(TEAM_ID + 1, "$pageview", uuid4(), now - timedelta(hours=i)) for i in range(20)]
    outside_range = [(TEAM_ID, "$pageview", uuid4(), now - timedelta(days=30)) for _ in range(10)]

    cluster.any_host(partial(_insert_events, matching_events + other_event_name + other_team + outside_range)).result()

    assert cluster.any_host(partial(_count_events, TEAM_ID)).result() == 90
    assert cluster.any_host(partial(_count_events, TEAM_ID + 1)).result() == 20

    from posthog.dags.data_deletion_requests import DeletionRequestContext

    deletion_ctx = DeletionRequestContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        start_time=start_time,
        end_time=end_time,
        events=["$pageview"],
    )
    context = build_op_context()
    execute_event_deletion(context, cluster, deletion_ctx)

    # Matching events should be deleted
    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$pageview")).result() == 10  # only outside_range
    # Other events for same team should be untouched
    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$identify")).result() == 30
    # Other team's events should be untouched
    assert cluster.any_host(partial(_count_events, TEAM_ID + 1)).result() == 20


@pytest.mark.django_db
def test_execute_event_deletion_multiple_event_names(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    pageview_events = [(TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i)) for i in range(20)]
    screen_events = [(TEAM_ID, "$screen", uuid4(), now - timedelta(hours=i)) for i in range(15)]
    keep_events = [(TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i)) for i in range(10)]

    cluster.any_host(partial(_insert_events, pageview_events + screen_events + keep_events)).result()

    from posthog.dags.data_deletion_requests import DeletionRequestContext

    deletion_ctx = DeletionRequestContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        start_time=start_time,
        end_time=end_time,
        events=["$pageview", "$screen"],
    )
    context = build_op_context()
    execute_event_deletion(context, cluster, deletion_ctx)

    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$pageview")).result() == 0
    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$screen")).result() == 0
    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$identify")).result() == 10


@pytest.mark.django_db
def test_full_job_event_deletion(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    target_events = [(TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i)) for i in range(50)]
    keep_events = [(TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i)) for i in range(30)]

    cluster.any_host(partial(_insert_events, target_events + keep_events)).result()

    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=start_time,
        end_time=end_time,
        status=RequestStatus.APPROVED,
    )

    result = data_deletion_request_event_removal.execute_in_process(
        run_config={
            "ops": {
                "load_deletion_request": {
                    "config": {"request_id": str(request.pk)},
                },
            },
        },
        resources={"cluster": cluster},
    )
    assert result.success

    # Target events deleted
    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$pageview")).result() == 0
    # Other events untouched
    assert cluster.any_host(partial(_count_events_by_name, TEAM_ID, "$identify")).result() == 30

    # Status transitioned to COMPLETED
    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED
