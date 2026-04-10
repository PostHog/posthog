import json
from datetime import datetime, timedelta
from functools import partial
from uuid import uuid4

import pytest

from clickhouse_driver import Client
from dagster import build_op_context

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.data_deletion_requests import (
    DataDeletionRequestConfig,
    DeletionRequestContext,
    data_deletion_request_event_removal,
    data_deletion_request_property_removal,
    execute_event_deletion,
    load_deletion_request,
    load_property_removal_request,
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
