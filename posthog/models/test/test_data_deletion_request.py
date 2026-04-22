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


def test_hogql_predicate_valid_expression_passes(team):
    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="properties.$browser = 'Chrome'",
        )
    )
    request.clean()  # should not raise


def test_hogql_predicate_invalid_syntax_raises(team):
    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="this is not hogql",
        )
    )
    with pytest.raises(ValidationError, match="hogql_predicate"):
        request.clean()


def test_hogql_predicate_unknown_field_raises(team):
    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="nonexistent_column = 1",
        )
    )
    with pytest.raises(ValidationError, match="hogql_predicate"):
        request.clean()


def test_hogql_predicate_subquery_rejected(team):
    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="event IN (SELECT event FROM events)",
        )
    )
    with pytest.raises(ValidationError, match="Subqueries"):
        request.clean()


def test_hogql_predicate_blank_is_ignored(team):
    request = DataDeletionRequest(**_base_kwargs(team_id=team.id, events=["$pageview"], hogql_predicate=""))
    request.clean()  # should not raise


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
