import uuid as uuid_lib
from datetime import datetime, timedelta

import pytest

from django.core.exceptions import ValidationError

from posthog.models.data_deletion_request import DataDeletionRequest, RequestType
from posthog.models.organization import Organization
from posthog.models.team import Team

TEAM_ID = 99999


@pytest.fixture
def team(db):
    org = Organization.objects.create(name="test-org")
    return Team.objects.create(organization=org, name="test-team")


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


@pytest.mark.parametrize(
    "predicate, error_match",
    [
        ("properties.$browser = 'Chrome'", None),
        ("", None),
        ("this is not hogql", "hogql_predicate"),
        ("nonexistent_column = 1", "hogql_predicate"),
        ("event IN (SELECT event FROM events)", "Subqueries"),
    ],
    ids=["valid", "blank", "invalid_syntax", "unknown_field", "subquery"],
)
def test_hogql_predicate_validation(team, predicate, error_match):
    request = DataDeletionRequest(
        **_base_kwargs(team_id=team.id, events=["$pageview"], hogql_predicate=predicate),
    )
    if error_match is None:
        request.clean()
    else:
        with pytest.raises(ValidationError, match=error_match):
            request.clean()


def test_compile_hogql_predicate_returns_sql_and_values(team):
    from posthog.models.data_deletion_request import compile_hogql_predicate

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="properties.$browser = 'Chrome'",
        )
    )
    sql, values = compile_hogql_predicate(request)
    assert sql
    assert values
    # The literal 'Chrome' should be parameterised rather than inlined into the SQL.
    assert "Chrome" not in sql
    assert "Chrome" in values.values()


def test_compile_hogql_predicate_empty_returns_empty():
    from posthog.models.data_deletion_request import compile_hogql_predicate

    request = DataDeletionRequest(**_base_kwargs(hogql_predicate=""))
    assert compile_hogql_predicate(request) == ("", {})


def test_rendered_count_query_substitutes_parameters():
    from posthog.admin.admins.data_deletion_request_admin import build_deletion_count_query
    from posthog.clickhouse.client.escape import substitute_params_for_display

    request = DataDeletionRequest(
        **_base_kwargs(
            events=["$pageview", "$identify"],
            start_time=datetime(2026, 4, 1),
            end_time=datetime(2026, 4, 15),
        )
    )
    template, params = build_deletion_count_query(request)
    rendered = substitute_params_for_display(template, params)

    assert "team_id = 99999" in rendered
    assert "timestamp >= '2026-04-01 00:00:00'" in rendered
    assert "timestamp < '2026-04-15 00:00:00'" in rendered
    assert "'$pageview'" in rendered
    assert "'$identify'" in rendered
    # No un-substituted placeholders left.
    assert "%(" not in rendered


def test_rendered_count_query_omits_event_filter_when_delete_all_events(team):
    from posthog.admin.admins.data_deletion_request_admin import build_deletion_count_query
    from posthog.clickhouse.client.escape import substitute_params_for_display

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=[],
            delete_all_events=True,
            start_time=datetime(2026, 4, 1),
            end_time=datetime(2026, 4, 15),
        )
    )
    template, params = build_deletion_count_query(request)
    rendered = substitute_params_for_display(template, params)

    assert "event IN" not in rendered
    assert "events" not in params


def test_rendered_count_query_includes_hogql_predicate(team):
    from posthog.admin.admins.data_deletion_request_admin import build_deletion_count_query
    from posthog.clickhouse.client.escape import substitute_params_for_display

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="properties.$browser = 'Chrome'",
        )
    )
    template, params = build_deletion_count_query(request)
    rendered = substitute_params_for_display(template, params)

    # The compiled HogQL fragment is ANDed on and its literal is substituted.
    assert "AND (" in rendered
    assert "'Chrome'" in rendered
    assert "%(" not in rendered


def _person_kwargs(**overrides) -> dict:
    kwargs = {
        "team_id": TEAM_ID,
        "request_type": RequestType.PERSON_REMOVAL,
        "start_time": None,
        "end_time": None,
        "person_uuids": [str(uuid_lib.uuid4())],
        "person_distinct_ids": [],
        "person_drop_profiles": True,
        "person_drop_events": False,
        "person_drop_recordings": False,
    }
    kwargs.update(overrides)
    return kwargs


def test_person_removal_clean_passes_minimal():
    request = DataDeletionRequest(**_person_kwargs())
    request.clean()


def test_person_removal_requires_at_least_one_selector():
    request = DataDeletionRequest(**_person_kwargs(person_uuids=[], person_distinct_ids=[]))
    with pytest.raises(ValidationError, match="person_uuids"):
        request.clean()


def test_person_removal_requires_at_least_one_action():
    request = DataDeletionRequest(
        **_person_kwargs(person_drop_profiles=False, person_drop_events=False, person_drop_recordings=False)
    )
    with pytest.raises(ValidationError, match="At least one of person_drop"):
        request.clean()


def test_person_removal_caps_total_selectors_at_1000():
    request = DataDeletionRequest(**_person_kwargs(person_uuids=[str(uuid_lib.uuid4()) for _ in range(1001)]))
    with pytest.raises(ValidationError, match="1000"):
        request.clean()


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"events": ["$pageview"]}, "events"),
        ({"delete_all_events": True}, "events"),
        ({"properties": ["$ip"]}, "properties"),
        ({"hogql_predicate": "properties.$browser = 'Chrome'"}, "hogql_predicate"),
    ],
    ids=["events", "delete_all_events", "properties", "hogql_predicate"],
)
def test_person_removal_rejects_event_only_fields(overrides, match):
    request = DataDeletionRequest(**_person_kwargs(**overrides))
    with pytest.raises(ValidationError, match=match):
        request.clean()


def _property_kwargs(**overrides) -> dict:
    kwargs = _base_kwargs(
        request_type=RequestType.PROPERTY_REMOVAL,
        properties=["$ip"],
    )
    kwargs.update(overrides)
    return kwargs


@pytest.mark.parametrize(
    "request_type, overrides, match",
    [
        (RequestType.EVENT_REMOVAL, {"person_uuids": [str(uuid_lib.uuid4())]}, "person_uuids"),
        (RequestType.EVENT_REMOVAL, {"person_distinct_ids": ["did-1"]}, "person_uuids"),
        (RequestType.EVENT_REMOVAL, {"person_drop_profiles": True}, "person_drop_profiles"),
        (RequestType.EVENT_REMOVAL, {"person_drop_events": True}, "person_drop_profiles"),
        (RequestType.EVENT_REMOVAL, {"person_drop_recordings": True}, "person_drop_profiles"),
        (RequestType.PROPERTY_REMOVAL, {"person_uuids": [str(uuid_lib.uuid4())]}, "person_uuids"),
        (RequestType.PROPERTY_REMOVAL, {"person_distinct_ids": ["did-1"]}, "person_uuids"),
        (RequestType.PROPERTY_REMOVAL, {"person_drop_profiles": True}, "person_drop_profiles"),
        (RequestType.PROPERTY_REMOVAL, {"person_drop_events": True}, "person_drop_profiles"),
        (RequestType.PROPERTY_REMOVAL, {"person_drop_recordings": True}, "person_drop_profiles"),
    ],
)
def test_event_and_property_removal_rejects_person_fields(request_type, overrides, match):
    if request_type == RequestType.EVENT_REMOVAL:
        kwargs = _base_kwargs(events=["$pageview"], **overrides)
    else:
        kwargs = _property_kwargs(**overrides)
    request = DataDeletionRequest(**kwargs)
    with pytest.raises(ValidationError, match=match):
        request.clean()
