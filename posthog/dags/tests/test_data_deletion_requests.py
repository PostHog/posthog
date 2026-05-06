import json
from datetime import datetime, timedelta
from functools import partial
from uuid import uuid4

import pytest
from unittest.mock import patch

import dagster
from clickhouse_driver import Client
from dagster import build_op_context

from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.data_deletion_requests import (
    DataDeletionRequestConfig,
    DeletionRequestContext,
    PersonRemovalContext,
    data_deletion_request_event_removal,
    data_deletion_request_person_removal,
    data_deletion_request_pickup_sensor,
    data_deletion_request_property_removal,
    delete_person_events_op,
    delete_person_profiles_op,
    delete_person_recordings_op,
    execute_event_deletion,
    finalize_deletion_request,
    load_deletion_request,
    load_person_removal_request,
    load_property_removal_request,
)
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType
from posthog.models.person import Person

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


def _insert_events_with_person(events: list[tuple], client: Client) -> None:
    client.execute(
        "INSERT INTO writable_events (team_id, event, uuid, timestamp, person_id) VALUES",
        events,
    )


def _count_events_for_person(team_id: int, person_uuid: str, client: Client) -> int:
    result = client.execute(
        "SELECT count() FROM writable_events WHERE team_id = %(team_id)s AND person_id = %(p)s",
        {"team_id": team_id, "p": person_uuid},
    )
    return result[0][0]


def _truncate_writable_events(client: Client) -> None:
    client.execute("TRUNCATE TABLE IF EXISTS sharded_events")


def _truncate_adhoc_events_deletion(client: Client) -> None:
    client.execute(f"TRUNCATE TABLE IF EXISTS {ADHOC_EVENTS_DELETION_TABLE}")


def _adhoc_pending_uuids(team_id: int, client: Client) -> set:
    result = client.execute(
        f"SELECT uuid FROM {ADHOC_EVENTS_DELETION_TABLE} FINAL WHERE team_id = %(team_id)s AND is_deleted = 0",
        {"team_id": team_id},
    )
    return {row[0] for row in result}


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
    assert request.attempt_count == 1
    assert request.first_executed_at is not None
    assert request.last_executed_at == request.first_executed_at


@pytest.mark.django_db
def test_load_deletion_request_increments_attempt_on_retry():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )
    config = DataDeletionRequestConfig(request_id=str(request.pk))

    load_deletion_request(build_op_context(), config)
    request.refresh_from_db()
    first_attempt_at = request.first_executed_at
    first_last_at = request.last_executed_at
    assert first_attempt_at is not None
    assert first_last_at is not None

    DataDeletionRequest.objects.filter(pk=request.pk).update(status=RequestStatus.APPROVED)

    load_deletion_request(build_op_context(), config)
    request.refresh_from_db()

    assert request.attempt_count == 2
    assert request.first_executed_at == first_attempt_at
    assert request.last_executed_at is not None
    assert request.last_executed_at >= first_last_at


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
@pytest.mark.parametrize(
    "execution_mode, expected_status",
    [
        (ExecutionMode.IMMEDIATE, RequestStatus.COMPLETED),
        (ExecutionMode.DEFERRED, RequestStatus.QUEUED),
    ],
)
def test_finalize_deletion_request_transitions_status(execution_mode, expected_status):
    start_time = datetime.now() - timedelta(days=7)
    end_time = datetime.now()
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=start_time,
        end_time=end_time,
        status=RequestStatus.IN_PROGRESS,
        execution_mode=execution_mode,
    )

    deletion_ctx = DeletionRequestContext(
        request_id=str(request.pk),
        team_id=TEAM_ID,
        start_time=start_time,
        end_time=end_time,
        events=["$pageview"],
        execution_mode=execution_mode.value,
    )
    context = build_op_context()
    finalize_deletion_request(context, deletion_ctx)

    request.refresh_from_db()
    assert request.status == expected_status


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
def test_execute_event_deletion_delete_all_events_drops_every_event_for_team(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    team_events = [
        (TEAM_ID, name, uuid4(), now - timedelta(hours=i))
        for i in range(10)
        for name in ("$pageview", "$identify", "$screen")
    ]
    other_team_events = [(TEAM_ID + 1, "$pageview", uuid4(), now - timedelta(hours=i)) for i in range(10)]
    outside_range = [(TEAM_ID, "$pageview", uuid4(), now - timedelta(days=30)) for _ in range(5)]

    cluster.any_host(partial(_insert_events, team_events + other_team_events + outside_range)).result()

    assert cluster.any_host(partial(_count_events, TEAM_ID)).result() == 35

    deletion_ctx = DeletionRequestContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        start_time=start_time,
        end_time=end_time,
        events=[],
        delete_all_events=True,
    )
    context = build_op_context()
    execute_event_deletion(context, cluster, deletion_ctx)

    # Every event for the team within the time range is gone (only outside_range survives).
    assert cluster.any_host(partial(_count_events, TEAM_ID)).result() == 5
    # Other team untouched.
    assert cluster.any_host(partial(_count_events, TEAM_ID + 1)).result() == 10


@pytest.mark.django_db
def test_execute_event_deletion_applies_hogql_predicate(cluster: ClickhouseCluster):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    org = Organization.objects.create(name="test-org-hogql")
    team = Team.objects.create(organization=org, name="test-team-hogql")

    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    chrome_events = [
        (team.id, "$pageview", uuid4(), now - timedelta(hours=i), '{"$browser": "Chrome"}') for i in range(10)
    ]
    firefox_events = [
        (team.id, "$pageview", uuid4(), now - timedelta(hours=i), '{"$browser": "Firefox"}') for i in range(5)
    ]

    cluster.any_host(partial(_insert_events_with_properties, chrome_events + firefox_events)).result()
    assert cluster.any_host(partial(_count_events_by_name, team.id, "$pageview")).result() == 15

    deletion_ctx = DeletionRequestContext(
        request_id=str(uuid4()),
        team_id=team.id,
        start_time=start_time,
        end_time=end_time,
        events=["$pageview"],
        hogql_predicate="properties.$browser = 'Chrome'",
    )
    context = build_op_context()
    execute_event_deletion(context, cluster, deletion_ctx)

    # Only the Chrome events should be deleted; Firefox events remain.
    assert cluster.any_host(partial(_count_events_by_name, team.id, "$pageview")).result() == 5


@pytest.mark.django_db
def test_execute_event_deletion_multiple_event_names(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    pageview_events = [(TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i)) for i in range(20)]
    screen_events = [(TEAM_ID, "$screen", uuid4(), now - timedelta(hours=i)) for i in range(15)]
    keep_events = [(TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i)) for i in range(10)]

    cluster.any_host(partial(_insert_events, pageview_events + screen_events + keep_events)).result()

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


# ---------------------------------------------------------------------------
# Deferred event-removal tests
# ---------------------------------------------------------------------------

DEFERRED_TEAM_ID = 77777


@pytest.mark.django_db
def test_execute_event_deletion_deferred_queues_into_adhoc_table(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    cluster.any_host(_truncate_adhoc_events_deletion).result()

    matching_uuids = [uuid4() for _ in range(25)]
    matching_events = [
        (DEFERRED_TEAM_ID, "$pageview", u, now - timedelta(hours=i)) for i, u in enumerate(matching_uuids)
    ]
    other_events = [(DEFERRED_TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i)) for i in range(10)]

    cluster.any_host(partial(_insert_events, matching_events + other_events)).result()

    deletion_ctx = DeletionRequestContext(
        request_id=str(uuid4()),
        team_id=DEFERRED_TEAM_ID,
        start_time=start_time,
        end_time=end_time,
        events=["$pageview"],
        execution_mode=ExecutionMode.DEFERRED.value,
    )
    context = build_op_context()
    execute_event_deletion(context, cluster, deletion_ctx)

    # Events NOT deleted.
    assert cluster.any_host(partial(_count_events_by_name, DEFERRED_TEAM_ID, "$pageview")).result() == 25
    # UUIDs queued.
    queued = cluster.any_host(partial(_adhoc_pending_uuids, DEFERRED_TEAM_ID)).result()
    assert queued == set(matching_uuids)

    cluster.any_host(_truncate_adhoc_events_deletion).result()


@pytest.mark.django_db
def test_full_job_event_deletion_deferred(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    cluster.any_host(_truncate_adhoc_events_deletion).result()

    target_uuids = [uuid4() for _ in range(15)]
    target_events = [(DEFERRED_TEAM_ID, "$pageview", u, now - timedelta(hours=i)) for i, u in enumerate(target_uuids)]
    keep_events = [(DEFERRED_TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i)) for i in range(10)]

    cluster.any_host(partial(_insert_events, target_events + keep_events)).result()

    request = DataDeletionRequest.objects.create(
        team_id=DEFERRED_TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=start_time,
        end_time=end_time,
        status=RequestStatus.APPROVED,
        execution_mode=ExecutionMode.DEFERRED,
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

    assert cluster.any_host(partial(_count_events_by_name, DEFERRED_TEAM_ID, "$pageview")).result() == 15
    queued = cluster.any_host(partial(_adhoc_pending_uuids, DEFERRED_TEAM_ID)).result()
    assert queued == set(target_uuids)

    request.refresh_from_db()
    assert request.status == RequestStatus.QUEUED

    cluster.any_host(_truncate_adhoc_events_deletion).result()


@pytest.mark.django_db
def test_verify_queued_promotes_when_events_gone():
    from posthog.dags.data_deletion_requests import _count_remaining_matching_events

    now = datetime.now()
    request = DataDeletionRequest.objects.create(
        team_id=DEFERRED_TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=now - timedelta(days=7),
        end_time=now + timedelta(minutes=1),
        status=RequestStatus.QUEUED,
        execution_mode=ExecutionMode.DEFERRED,
    )

    assert _count_remaining_matching_events(request) == 0

    from django.utils import timezone

    DataDeletionRequest.objects.filter(pk=request.pk, status=RequestStatus.QUEUED).update(
        status=RequestStatus.COMPLETED, updated_at=timezone.now()
    )

    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED


# ---------------------------------------------------------------------------
# Property removal tests
# ---------------------------------------------------------------------------

PROP_TEAM_ID = 88888


def _insert_events_with_properties(events: list[tuple], client: Client) -> None:
    """Insert events with (team_id, event, uuid, timestamp, properties_json)."""
    client.execute(
        "INSERT INTO writable_events (team_id, event, uuid, timestamp, properties) VALUES",
        events,
    )


def _get_properties(team_id: int, event_name: str, client: Client) -> list[dict]:
    result = client.execute(
        "SELECT properties FROM events WHERE team_id = %(team_id)s AND event = %(event)s",
        {"team_id": team_id, "event": event_name},
    )
    return [json.loads(row[0]) for row in result]


def _get_mat_column_values(team_id: int, event_name: str, column: str, client: Client) -> list[str]:
    result = client.execute(
        f"SELECT `{column}` FROM events WHERE team_id = %(team_id)s AND event = %(event)s",
        {"team_id": team_id, "event": event_name},
    )
    return [row[0] for row in result]


@pytest.mark.django_db
def test_load_property_removal_request_transitions_to_in_progress():
    request = DataDeletionRequest.objects.create(
        team_id=PROP_TEAM_ID,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["$pageview"],
        properties=["$ip", "metrics"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )

    config = DataDeletionRequestConfig(request_id=str(request.pk))
    context = build_op_context()
    result = load_property_removal_request(context, config)

    assert result.team_id == PROP_TEAM_ID
    assert result.properties == ["$ip", "metrics"]

    request.refresh_from_db()
    assert request.status == RequestStatus.IN_PROGRESS


@pytest.mark.django_db
def test_load_property_removal_request_rejects_event_removal():
    request = DataDeletionRequest.objects.create(
        team_id=PROP_TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )

    config = DataDeletionRequestConfig(request_id=str(request.pk))
    context = build_op_context()

    with pytest.raises(Exception, match="not an approved property_removal request"):
        load_property_removal_request(context, config)


@pytest.mark.django_db
def test_load_property_removal_request_rejects_empty_properties():
    request = DataDeletionRequest.objects.create(
        team_id=PROP_TEAM_ID,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["$pageview"],
        properties=[],
        start_time=datetime.now() - timedelta(days=7),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )

    config = DataDeletionRequestConfig(request_id=str(request.pk))
    context = build_op_context()

    with pytest.raises(Exception, match="no properties specified"):
        load_property_removal_request(context, config)


@pytest.mark.django_db
def test_full_job_property_removal(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    props_to_drop_obj = {
        "$ip": "1.2.3.4",
        "metrics": "data",
        "keep": "yes",
        "sub": {"prop": "value"},
        "sub2": {"a": "b", "c": "d"},
    }
    props_to_drop = json.dumps(props_to_drop_obj)
    no_target_props = json.dumps({"keep": "yes", "other": "value"})

    target_events = [(PROP_TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i), props_to_drop) for i in range(30)]
    events_without_props = [
        (PROP_TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i), no_target_props) for i in range(20)
    ]
    other_event = [(PROP_TEAM_ID, "$identify", uuid4(), now - timedelta(hours=i), props_to_drop) for i in range(10)]

    cluster.any_host(
        partial(_insert_events_with_properties, target_events + events_without_props + other_event)
    ).result()

    # Precondition: all events present
    assert cluster.any_host(partial(_count_events_by_name, PROP_TEAM_ID, "$pageview")).result() == 50
    assert cluster.any_host(partial(_count_events_by_name, PROP_TEAM_ID, "$identify")).result() == 10

    request = DataDeletionRequest.objects.create(
        team_id=PROP_TEAM_ID,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["$pageview"],
        properties=["$ip", "metrics", "sub.prop", "sub2.a"],
        start_time=start_time,
        end_time=end_time,
        status=RequestStatus.APPROVED,
    )

    result = data_deletion_request_property_removal.execute_in_process(
        run_config={
            "ops": {
                "load_property_removal_request": {
                    "config": {"request_id": str(request.pk)},
                },
            },
        },
        resources={"cluster": cluster},
    )
    assert result.success

    # Events still exist (not deleted, only properties modified)
    assert cluster.any_host(partial(_count_events_by_name, PROP_TEAM_ID, "$pageview")).result() == 50

    # Target properties removed from matching events
    pageview_props = cluster.any_host(partial(_get_properties, PROP_TEAM_ID, "$pageview")).result()
    for props in pageview_props:
        assert "$ip" not in props, f"$ip should be removed, got {props}"
        assert "metrics" not in props, f"metrics should be removed, got {props}"
        assert "prop" not in props.get("sub", {}), f"sub.prop should be removed, got {props}"
        assert "keep" in props, f"keep should be preserved, got {props}"
        sub = props.get("sub2", None)
        if sub is not None:
            assert "a" not in sub, f"sub.prop should be removed, got {props}"
            assert "c" in sub, f"sub.prop should be preserved, got {props}"

    # $identify events untouched (different event name, not in request)
    identify_props = cluster.any_host(partial(_get_properties, PROP_TEAM_ID, "$identify")).result()
    for props in identify_props:
        assert props_to_drop_obj == props, f"Properties should not be modified, got {props}"

    # Status transitioned to COMPLETED
    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED


@pytest.mark.django_db
def test_full_job_property_removal_single_property(cluster: ClickhouseCluster):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    props = json.dumps({"secret": "value", "keep_me": "yes"})
    events = [(PROP_TEAM_ID, "custom_event", uuid4(), now - timedelta(hours=i), props) for i in range(20)]

    cluster.any_host(partial(_insert_events_with_properties, events)).result()

    request = DataDeletionRequest.objects.create(
        team_id=PROP_TEAM_ID,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["custom_event"],
        properties=["secret"],
        start_time=start_time,
        end_time=end_time,
        status=RequestStatus.APPROVED,
    )

    result = data_deletion_request_property_removal.execute_in_process(
        run_config={
            "ops": {
                "load_property_removal_request": {
                    "config": {"request_id": str(request.pk)},
                },
            },
        },
        resources={"cluster": cluster},
    )
    assert result.success

    all_props = cluster.any_host(partial(_get_properties, PROP_TEAM_ID, "custom_event")).result()
    for event_props in all_props:
        assert "secret" not in event_props
        assert "keep_me" in event_props

    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED


@pytest.mark.django_db
def test_full_job_property_removal_applies_hogql_predicate(cluster: ClickhouseCluster):
    """A property removal scoped by hogql_predicate must clean only matching events."""
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    org = Organization.objects.create(name="test-org-prop-hogql")
    team = Team.objects.create(organization=org, name="test-team-prop-hogql")

    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    chrome_props = json.dumps({"secret": "value", "$browser": "Chrome"})
    firefox_props = json.dumps({"secret": "value", "$browser": "Firefox"})
    chrome_events = [(team.id, "$pageview", uuid4(), now - timedelta(hours=i), chrome_props) for i in range(10)]
    firefox_events = [(team.id, "$pageview", uuid4(), now - timedelta(hours=i), firefox_props) for i in range(5)]

    cluster.any_host(partial(_insert_events_with_properties, chrome_events + firefox_events)).result()

    request = DataDeletionRequest.objects.create(
        team_id=team.id,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["$pageview"],
        properties=["secret"],
        start_time=start_time,
        end_time=end_time,
        hogql_predicate="properties.$browser = 'Chrome'",
        status=RequestStatus.APPROVED,
    )

    result = data_deletion_request_property_removal.execute_in_process(
        run_config={
            "ops": {
                "load_property_removal_request": {
                    "config": {"request_id": str(request.pk)},
                },
            },
        },
        resources={"cluster": cluster},
    )
    assert result.success

    # Chrome events: secret cleaned, $browser preserved
    all_props = cluster.any_host(partial(_get_properties, team.id, "$pageview")).result()
    chrome = [p for p in all_props if p.get("$browser") == "Chrome"]
    firefox = [p for p in all_props if p.get("$browser") == "Firefox"]
    assert len(chrome) == 10, f"expected 10 Chrome rows, got {len(chrome)}"
    assert len(firefox) == 5, f"expected 5 Firefox rows untouched, got {len(firefox)}"
    for props in chrome:
        assert "secret" not in props, f"Chrome event still has secret: {props}"
    for props in firefox:
        assert props.get("secret") == "value", f"Firefox event must keep secret: {props}"


def _assert_subfield_removed(props: dict, path: str) -> None:
    """Assert a dotted subfield path was removed from props."""
    parts = path.split(".")
    obj = props
    for part in parts[:-1]:
        obj = obj.get(part, {})
    assert parts[-1] not in obj, f"{path} should be removed, got {props}"


def _assert_subfield_present(props: dict, path: str, expected_value: object) -> None:
    """Assert a dotted subfield path is present with expected value.

    Skips if a parent key is missing (control event that never had this structure).
    """
    parts = path.split(".")
    obj = props
    for part in parts[:-1]:
        child = obj.get(part)
        if child is None:
            return
        obj = child
    assert obj.get(parts[-1]) == expected_value, f"{path} should be {expected_value}, got {props}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "properties, target_props_obj, expected_removed, expected_preserved",
    [
        pytest.param(
            ["sub.prop", "sub2.a"],
            {"keep": "yes", "sub": {"prop": "value", "other": "keep"}, "sub2": {"a": "b", "c": "d"}},
            ["sub.prop", "sub2.a"],
            [("keep", "yes"), ("sub.other", "keep"), ("sub2.c", "d")],
            id="multiple_subfields",
        ),
        pytest.param(
            ["nested.secret"],
            {"keep": "yes", "nested": {"secret": "value", "visible": "ok"}},
            ["nested.secret"],
            [("keep", "yes"), ("nested.visible", "ok")],
            id="single_subfield",
        ),
    ],
)
def test_full_job_property_removal_subfield_only(
    cluster: ClickhouseCluster,
    properties: list[str],
    target_props_obj: dict,
    expected_removed: list[str],
    expected_preserved: list[tuple[str, object]],
):
    now = datetime.now()
    start_time = now - timedelta(days=7)
    end_time = now + timedelta(minutes=1)

    target_props = json.dumps(target_props_obj)
    no_target_props = json.dumps({"keep": "yes", "other": "value"})

    target_events = [(PROP_TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i), target_props) for i in range(30)]
    control_events = [
        (PROP_TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i), no_target_props) for i in range(20)
    ]

    cluster.any_host(partial(_insert_events_with_properties, target_events + control_events)).result()

    request = DataDeletionRequest.objects.create(
        team_id=PROP_TEAM_ID,
        request_type=RequestType.PROPERTY_REMOVAL,
        events=["$pageview"],
        properties=properties,
        start_time=start_time,
        end_time=end_time,
        status=RequestStatus.APPROVED,
    )

    result = data_deletion_request_property_removal.execute_in_process(
        run_config={
            "ops": {
                "load_property_removal_request": {
                    "config": {"request_id": str(request.pk)},
                },
            },
        },
        resources={"cluster": cluster},
    )
    assert result.success

    assert cluster.any_host(partial(_count_events_by_name, PROP_TEAM_ID, "$pageview")).result() == 50

    all_props = cluster.any_host(partial(_get_properties, PROP_TEAM_ID, "$pageview")).result()
    for props in all_props:
        for path in expected_removed:
            _assert_subfield_removed(props, path)
        for path, value in expected_preserved:
            _assert_subfield_present(props, path, value)

    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED


def _add_default_mat_columns(col_defs: list[tuple[str, str, str]], client: Client) -> None:
    """Add DEFAULT materialized columns to events tables for testing.

    Each entry is (col_name, prop_name, col_type).
    """
    from django.conf import settings

    db = settings.CLICKHOUSE_DATABASE
    for col_name, prop_name, col_type in col_defs:
        comment = f"column_materializer::properties::{prop_name}"
        for table in ("sharded_events", "events"):
            kw = f"COMMENT '{comment}'" if table == "events" else ""
            client.execute(
                f"ALTER TABLE {db}.{table} "
                f"ADD COLUMN IF NOT EXISTS `{col_name}` {col_type} "
                f"DEFAULT JSONExtractRaw(properties, '{prop_name}') "
                f"{kw}"
            )


def _drop_default_mat_columns(col_defs: list[tuple[str, str, str]], client: Client) -> None:
    from django.conf import settings

    db = settings.CLICKHOUSE_DATABASE
    for col_name, _prop, _typ in col_defs:
        for table in ("sharded_events", "events"):
            client.execute(f"ALTER TABLE {db}.{table} DROP COLUMN IF EXISTS `{col_name}`")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "col_defs, properties_to_delete, expected_empty_cols",
    [
        pytest.param(
            [("mat_test_single", "test_single", "String")],
            ["test_single"],
            ["mat_test_single"],
            id="single_property",
        ),
        pytest.param(
            [
                ("mat_test_a", "test_a", "String"),
                ("mat_test_b", "test_b", "Nullable(String)"),
            ],
            ["test_a", "test_b"],
            ["mat_test_a", "mat_test_b"],
            id="multiple_properties_mixed_nullable",
        ),
    ],
)
def test_full_job_property_removal_clears_materialized_columns(
    cluster: ClickhouseCluster,
    col_defs: list[tuple[str, str, str]],
    properties_to_delete: list[str],
    expected_empty_cols: list[str],
):
    cluster.any_host(partial(_add_default_mat_columns, col_defs)).result()

    try:
        now = datetime.now()
        start_time = now - timedelta(days=7)
        end_time = now + timedelta(minutes=1)

        target_props = {prop: "secret" for _, prop, _ in col_defs}
        target_props["keep"] = "yes"
        props_with_target = json.dumps(target_props)
        props_without_target = json.dumps({"keep": "yes", "other": "value"})

        target_events = [
            (PROP_TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i), props_with_target) for i in range(20)
        ]
        control_events = [
            (PROP_TEAM_ID, "$pageview", uuid4(), now - timedelta(hours=i), props_without_target) for i in range(10)
        ]

        cluster.any_host(partial(_insert_events_with_properties, target_events + control_events)).result()

        # Precondition: DEFAULT mat columns have values
        for col_name in expected_empty_cols:
            mat_values = cluster.any_host(partial(_get_mat_column_values, PROP_TEAM_ID, "$pageview", col_name)).result()
            assert any(v and "secret" in v for v in mat_values), f"expected secret in {col_name}, got {set(mat_values)}"

        request = DataDeletionRequest.objects.create(
            team_id=PROP_TEAM_ID,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=properties_to_delete,
            start_time=start_time,
            end_time=end_time,
            status=RequestStatus.APPROVED,
        )

        result = data_deletion_request_property_removal.execute_in_process(
            run_config={
                "ops": {
                    "load_property_removal_request": {
                        "config": {"request_id": str(request.pk)},
                    },
                },
            },
            resources={"cluster": cluster},
        )
        assert result.success

        assert cluster.any_host(partial(_count_events_by_name, PROP_TEAM_ID, "$pageview")).result() == 30

        all_props = cluster.any_host(partial(_get_properties, PROP_TEAM_ID, "$pageview")).result()
        for props in all_props:
            for prop in properties_to_delete:
                assert prop not in props, f"{prop} should be removed, got {props}"
            assert "keep" in props, f"keep should be preserved, got {props}"

        # DEFAULT materialized columns cleared
        for col_name in expected_empty_cols:
            mat_values = cluster.any_host(partial(_get_mat_column_values, PROP_TEAM_ID, "$pageview", col_name)).result()
            non_empty = [v for v in mat_values if v and v not in ("", None)]
            assert not non_empty, f"{col_name} should be empty, got non-empty values: {set(non_empty)}"

        request.refresh_from_db()
        assert request.status == RequestStatus.COMPLETED
    finally:
        cluster.any_host(partial(_drop_default_mat_columns, col_defs)).result()


@pytest.mark.django_db
def test_load_person_removal_request_transitions_to_in_progress():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.PERSON_REMOVAL,
        person_uuids=[str(uuid4())],
        person_drop_profiles=True,
        person_drop_events=True,
        person_drop_recordings=False,
        status=RequestStatus.APPROVED,
    )
    config = DataDeletionRequestConfig(request_id=str(request.pk))
    ctx = build_op_context()

    result = load_person_removal_request(ctx, config)

    assert result.team_id == TEAM_ID
    assert result.drop_profiles is True
    assert result.drop_events is True
    assert result.drop_recordings is False
    request.refresh_from_db()
    assert request.status == RequestStatus.IN_PROGRESS


@pytest.mark.django_db
def test_load_person_removal_rejects_both_selectors():
    # Belt-and-suspenders: model.clean() enforces mutual exclusion at the API boundary, but if
    # a row is created bypassing clean() (e.g. raw SQL or .objects.create), the dagster job must
    # still refuse to run because resolve_persons_for_deletion's elif would silently drop one set.
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.PERSON_REMOVAL,
        person_uuids=[str(uuid4())],
        person_distinct_ids=["did-1"],
        person_drop_profiles=True,
        person_drop_events=False,
        person_drop_recordings=False,
        status=RequestStatus.APPROVED,
    )
    config = DataDeletionRequestConfig(request_id=str(request.pk))
    with pytest.raises(Exception, match="mutually exclusive"):
        load_person_removal_request(build_op_context(), config)


@pytest.mark.django_db
def test_load_person_removal_rejects_wrong_type():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime.now() - timedelta(days=1),
        end_time=datetime.now(),
        status=RequestStatus.APPROVED,
    )
    config = DataDeletionRequestConfig(request_id=str(request.pk))
    with pytest.raises(Exception, match="not an approved person_removal request"):
        load_person_removal_request(build_op_context(), config)


@pytest.mark.django_db
def test_delete_person_events_op_runs_lightweight_delete_per_shard(cluster: ClickhouseCluster):
    person_uuid = str(uuid4())
    other_uuid = str(uuid4())
    now = datetime.now()

    cluster.any_host(_truncate_writable_events).result()
    cluster.any_host(
        partial(
            _insert_events_with_person,
            [
                (TEAM_ID, "$pageview", str(uuid4()), now, person_uuid),
                (TEAM_ID, "$pageview", str(uuid4()), now, other_uuid),
            ],
        )
    ).result()

    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[person_uuid],
        person_distinct_ids=[],
        drop_profiles=False,
        drop_events=True,
        drop_recordings=False,
    )

    delete_person_events_op(build_op_context(), cluster, ctx)

    assert cluster.any_host(partial(_count_events_for_person, TEAM_ID, person_uuid)).result() == 0
    assert cluster.any_host(partial(_count_events_for_person, TEAM_ID, other_uuid)).result() == 1


@pytest.mark.django_db
def test_delete_person_events_op_noop_when_disabled(cluster: ClickhouseCluster):
    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[str(uuid4())],
        person_distinct_ids=[],
        drop_profiles=False,
        drop_events=False,
        drop_recordings=False,
    )
    delete_person_events_op(build_op_context(), cluster, ctx)


@pytest.mark.django_db
def test_delete_person_events_op_resolves_distinct_ids_to_uuids(cluster: ClickhouseCluster):
    # When the request was submitted by distinct_id, the events op must resolve to UUIDs
    # because the CH events table is keyed by person_id (UUID).
    p = Person.objects.create(team_id=TEAM_ID, uuid=uuid4(), distinct_ids=["distinct-only"])
    bystander_uuid = str(uuid4())
    now = datetime.now()

    cluster.any_host(_truncate_writable_events).result()
    cluster.any_host(
        partial(
            _insert_events_with_person,
            [
                (TEAM_ID, "$pageview", str(uuid4()), now, str(p.uuid)),
                (TEAM_ID, "$pageview", str(uuid4()), now, bystander_uuid),
            ],
        )
    ).result()

    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[],
        person_distinct_ids=["distinct-only"],
        drop_profiles=False,
        drop_events=True,
        drop_recordings=False,
    )

    delete_person_events_op(build_op_context(), cluster, ctx)

    assert cluster.any_host(partial(_count_events_for_person, TEAM_ID, str(p.uuid))).result() == 0
    assert cluster.any_host(partial(_count_events_for_person, TEAM_ID, bystander_uuid)).result() == 1


@pytest.mark.django_db
def test_delete_person_recordings_op_calls_helper_when_enabled():
    p_uuid = str(uuid4())
    Person.objects.create(team_id=TEAM_ID, uuid=p_uuid, distinct_ids=["a"])
    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[p_uuid],
        person_distinct_ids=[],
        drop_profiles=False,
        drop_events=False,
        drop_recordings=True,
    )
    with patch("posthog.dags.data_deletion_requests.queue_person_recording_deletion") as queue:
        delete_person_recordings_op(build_op_context(), ctx)
        queue.assert_called_once()
        kwargs = queue.call_args.kwargs
        assert kwargs["actor"] is None  # no DRF user in Dagster


@pytest.mark.django_db
def test_delete_person_recordings_op_noop_when_disabled():
    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[str(uuid4())],
        person_distinct_ids=[],
        drop_profiles=False,
        drop_events=False,
        drop_recordings=False,
    )
    with patch("posthog.dags.data_deletion_requests.queue_person_recording_deletion") as queue:
        delete_person_recordings_op(build_op_context(), ctx)
        queue.assert_not_called()


@pytest.mark.django_db
def test_delete_person_profiles_op_calls_helper_when_enabled():
    p_uuid = str(uuid4())
    Person.objects.create(team_id=TEAM_ID, uuid=p_uuid, distinct_ids=["a"])
    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[p_uuid],
        person_distinct_ids=[],
        drop_profiles=True,
        drop_events=False,
        drop_recordings=False,
    )
    with patch("posthog.dags.data_deletion_requests.delete_persons_profile") as deleter:
        deleter.return_value = type("R", (), {"deleted_count": 1, "errors": []})()
        delete_person_profiles_op(build_op_context(), ctx)
        deleter.assert_called_once()


@pytest.mark.django_db
def test_delete_person_profiles_op_noop_when_disabled():
    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[str(uuid4())],
        person_distinct_ids=[],
        drop_profiles=False,
        drop_events=False,
        drop_recordings=False,
    )
    with patch("posthog.dags.data_deletion_requests.delete_persons_profile") as deleter:
        delete_person_profiles_op(build_op_context(), ctx)
        deleter.assert_not_called()


@pytest.mark.django_db
def test_delete_person_profiles_op_records_per_person_errors_in_metadata():
    # Best-effort semantics: per-person failures are recorded in op metadata and surfaced via
    # logs, but the op returns normally so the request can finalize to COMPLETED and the
    # operator can issue a follow-up request for the failed UUIDs.
    p_uuid = str(uuid4())
    Person.objects.create(team_id=TEAM_ID, uuid=p_uuid, distinct_ids=["a"])
    ctx = PersonRemovalContext(
        request_id=str(uuid4()),
        team_id=TEAM_ID,
        person_uuids=[p_uuid],
        person_distinct_ids=[],
        drop_profiles=True,
        drop_events=False,
        drop_recordings=False,
    )
    op_context = build_op_context()
    with patch("posthog.dags.data_deletion_requests.delete_persons_profile") as deleter:
        deleter.return_value = type("R", (), {"deleted_count": 0, "errors": [p_uuid]})()
        with patch.object(op_context.log, "warning") as warn:
            result = delete_person_profiles_op(op_context, ctx)

    # No raise — best-effort, returns the context.
    assert result is ctx
    # The op surfaced the failure via a warning log so operators can find the failed UUIDs.
    assert warn.called
    warn_message = warn.call_args.args[0] if warn.call_args.args else ""
    assert "1 per-person failures" in warn_message


@pytest.mark.django_db
def test_data_deletion_request_person_removal_lifecycle(cluster: ClickhouseCluster):
    p_uuid = str(uuid4())
    Person.objects.create(team_id=TEAM_ID, uuid=p_uuid, distinct_ids=["a"])
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.PERSON_REMOVAL,
        person_uuids=[p_uuid],
        person_drop_profiles=True,
        person_drop_events=True,
        person_drop_recordings=False,
        status=RequestStatus.APPROVED,
    )

    with (
        patch("posthog.dags.data_deletion_requests.delete_persons_profile") as profile,
        patch("posthog.dags.data_deletion_requests.queue_person_recording_deletion"),
    ):
        profile.return_value = type("R", (), {"deleted_count": 1, "errors": []})()
        result = data_deletion_request_person_removal.execute_in_process(
            run_config={
                "ops": {
                    "load_person_removal_request": {"config": {"request_id": str(request.pk)}},
                },
            },
            resources={"cluster": cluster},
        )

    assert result.success
    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED


@pytest.mark.django_db
def test_pickup_sensor_routes_person_removal_request():
    request = DataDeletionRequest.objects.create(
        team_id=TEAM_ID,
        request_type=RequestType.PERSON_REMOVAL,
        person_uuids=[str(uuid4())],
        person_drop_profiles=True,
        status=RequestStatus.APPROVED,
        approved_at=datetime.now(),
    )
    instance = dagster.DagsterInstance.ephemeral()
    ctx = dagster.build_sensor_context(instance=instance)
    result = data_deletion_request_pickup_sensor(ctx)
    assert isinstance(result, dagster.RunRequest)
    assert result.job_name == "data_deletion_request_person_removal"
    assert "load_person_removal_request" in result.run_config["ops"]
    assert str(request.pk) == result.run_key
