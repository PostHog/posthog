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
