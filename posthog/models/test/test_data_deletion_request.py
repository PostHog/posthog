import uuid as uuid_lib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
import time_machine
from posthog.test.base import materialized
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models import data_deletion_request as ddr
from posthog.models.data_deletion_request import (
    DataDeletionRequest,
    RequestStatus,
    RequestType,
    auto_approve_blocker,
    cached_compile_hogql_predicate,
    compile_hogql_predicate,
    invalidate_compiled_predicate_cache,
    uncopied_rows_predicate,
)
from posthog.models.deletion_targets import FLAG_EVALUATIONS, FLAG_EVALUATIONS_HOGQL_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_SOURCE_EVENT
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.event_definitions.backend.models import PropertyDefinition

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "ddr-test"}}

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


def _recording_compile() -> tuple[list[str], Callable]:
    calls: list[str] = []

    def fake_compile(obj):
        calls.append(obj.hogql_predicate)
        return "equals(1, 1)", {"k": "v"}

    return calls, fake_compile


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


@pytest.mark.parametrize(
    "events,delete_all_events",
    [
        (["$pageview"], False),
        ([], True),
    ],
)
def test_property_removal_clean_passes(events, delete_all_events):
    request = DataDeletionRequest(
        **_base_kwargs(
            request_type=RequestType.PROPERTY_REMOVAL,
            events=events,
            properties=["$ip"],
            delete_all_events=delete_all_events,
        )
    )
    request.clean()


@pytest.mark.parametrize(
    "events,delete_all_events,match",
    [
        ([], False, "Provide at least one event"),
        (["$pageview"], True, "Events must be empty"),
    ],
)
def test_property_removal_clean_raises(events, delete_all_events, match):
    request = DataDeletionRequest(
        **_base_kwargs(
            request_type=RequestType.PROPERTY_REMOVAL,
            events=events,
            properties=["$ip"],
            delete_all_events=delete_all_events,
        )
    )
    with pytest.raises(ValidationError, match=match):
        request.clean()


@pytest.mark.parametrize(
    "predicate, error_match",
    [
        ("properties.$browser = 'Chrome'", None),
        ("", None),
        ("this is not hogql", "hogql_predicate"),
        ("nonexistent_column = 1", "hogql_predicate"),
        ("event IN (SELECT event FROM events)", None),
    ],
    ids=["valid", "blank", "invalid_syntax", "unknown_field", "subquery_allowed"],
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


@pytest.mark.parametrize(
    "predicate",
    [
        "person_id IN (SELECT id FROM persons WHERE properties.email = 'foo@example.com')",
        "event IN (SELECT event FROM events WHERE timestamp > now() - INTERVAL 1 DAY)",
    ],
    ids=["person_subquery", "events_subquery"],
)
def test_hogql_predicate_allows_subqueries(team, predicate):
    """Subqueries against persons / events / cohorts are allowed in deletion predicates.

    HogQL's table resolver injects the ``team_id`` guard into each subquery, so
    cross-team data cannot leak through; the team-scoping test below is the
    regression net for that invariant.
    """
    from posthog.models.data_deletion_request import compile_hogql_predicate

    request = DataDeletionRequest(
        **_base_kwargs(team_id=team.id, events=["$pageview"], hogql_predicate=predicate),
    )
    request.clean()
    sql, _ = compile_hogql_predicate(request)
    assert sql


def test_hogql_predicate_subquery_is_team_scoped(db):
    """Compiling the same person-subquery predicate for two different teams must
    splice each team's id into the inner WHERE clause — that's how HogQL prevents
    cross-team leaks via subqueries.
    """
    from posthog.models.data_deletion_request import compile_hogql_predicate

    org = Organization.objects.create(name="scoping-org")
    team_a = Team.objects.create(organization=org, name="team-a")
    team_b = Team.objects.create(organization=org, name="team-b")
    assert team_a.id != team_b.id

    predicate = "person_id IN (SELECT id FROM persons WHERE properties.email = 'foo@example.com')"

    req_a = DataDeletionRequest(**_base_kwargs(team_id=team_a.id, events=["$pageview"], hogql_predicate=predicate))
    req_b = DataDeletionRequest(**_base_kwargs(team_id=team_b.id, events=["$pageview"], hogql_predicate=predicate))

    sql_a, _ = compile_hogql_predicate(req_a)
    sql_b, _ = compile_hogql_predicate(req_b)

    # HogQL inlines ``team_id`` as a literal int (not a parameter), so the bare
    # team id appears directly in the SQL. Confirm each team's id shows up in
    # its own SQL but not in the other's, and the standard ``equals(team_id, …)``
    # guard shape is present — that's HogQL's table resolver wrapping the
    # ``persons`` subquery with the team scope.
    assert f"equals(team_id, {team_a.id})" in sql_a
    assert f"equals(team_id, {team_b.id})" in sql_b
    assert f"equals(team_id, {team_b.id})" not in sql_a
    assert f"equals(team_id, {team_a.id})" not in sql_b


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


def test_compile_hogql_predicate_emits_no_table_qualifier(team, snapshot):
    """Predicate is spliced into both ``SELECT … FROM events`` and ``DELETE FROM
    sharded_events WHERE …``, so the compiled SQL must use unqualified column
    references — neither ``events.`` nor ``sharded_events.``.

    Snapshots the full SQL fragment so any regression that re-introduces a table
    prefix is caught.
    """
    from posthog.models.data_deletion_request import compile_hogql_predicate

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="properties.$browser = 'Chrome' AND event = '$pageview'",
        )
    )
    sql, _ = compile_hogql_predicate(request)
    assert sql == snapshot


def test_compile_hogql_predicate_emits_unqualified_materialized_column(team, snapshot):
    """When a property has a materialized column, the printer emits the ``mat_<prop>``
    column without a table prefix. ClickHouse's lightweight DELETE rewrites the
    predicate into a mutation whose expression analyzer rejects table-qualified
    references, so ``sharded_events.mat_$current_url`` would fail with "Missing
    columns" even when the column exists on every replica.
    """
    from posthog.models.data_deletion_request import compile_hogql_predicate

    from ee.clickhouse.materialized_columns.analyze import materialize

    materialize("events", "$current_url")

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="properties.$current_url LIKE '%message=%'",
        )
    )
    sql, _ = compile_hogql_predicate(request)
    assert "events.`mat_$current_url`" not in sql
    assert "sharded_events.`mat_$current_url`" not in sql
    assert "`mat_$current_url`" in sql
    assert sql == snapshot


def test_compile_hogql_predicate_missing_team_raises_validation_error(db):
    """If the team no longer exists, compilation must raise ``ValidationError`` (not
    ``Team.DoesNotExist``) so ``Model.clean()`` callers keep their contract.
    """
    from posthog.models.data_deletion_request import compile_hogql_predicate

    request = DataDeletionRequest(
        **_base_kwargs(team_id=2**31 - 1, events=["$pageview"], hogql_predicate="properties.$browser = 'Chrome'")
    )
    with pytest.raises(ValidationError, match="team no longer exists"):
        compile_hogql_predicate(request)


@time_machine.travel("2026-06-17T12:00:00Z", tick=False)
def test_compile_hogql_predicate_boolean_person_property_not_coerced(team):
    """A boolean-typed person property compared to a non-``true``/``false`` string must not be
    coerced to Bool. The coercion (``accurateCastOrNull(transform(...), 'Bool')``) maps the
    stored value to NULL, so ``person.properties.isEnterprise = 'yes'`` would silently match
    nothing. Compiling with the team's modifiers routes it through the property-group map read
    instead, exactly as a regular HogQL query would.
    """
    from posthog.models.data_deletion_request import compile_hogql_predicate

    from products.event_definitions.backend.models import PropertyDefinition

    team.modifiers = {"propertyGroupsMode": "optimized"}
    team.save()

    PropertyDefinition.objects.create(
        team=team,
        name="isEnterprise",
        type=PropertyDefinition.Type.PERSON,
        property_type="Boolean",
    )

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            events=["$pageview"],
            hogql_predicate="person.properties.isEnterprise = 'yes'",
        )
    )
    sql, _ = compile_hogql_predicate(request)

    assert "person_properties_map_custom" in sql
    assert "accurateCastOrNull" not in sql
    assert "transform(" not in sql


@pytest.fixture
def materialized_browser():
    with materialized("events", "$browser"):
        yield


@pytest.fixture
def dmat_slot_for_plan(team):
    from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition

    from products.event_definitions.backend.models.property_definition import PropertyType

    prop_def = PropertyDefinition.objects.create(
        team=team,
        project_id=team.project_id,
        name="plan",
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )
    MaterializedColumnSlot.objects.create(
        team=team, property_definition=prop_def, slot_index=0, state=MaterializedColumnSlotState.READY
    )


def _flag_call_request(team: Team, hogql_predicate: str) -> DataDeletionRequest:
    # OPTIMIZED is the cloud setting. It makes events read non-$ keys and $feature/ keys from
    # property-group maps, which flag_evaluations does not have.
    team.modifiers = {"propertyGroupsMode": "optimized"}
    team.save()
    return DataDeletionRequest(
        **_base_kwargs(team_id=team.id, events=[FLAG_EVALUATIONS_SOURCE_EVENT], hogql_predicate=hogql_predicate)
    )


@pytest.mark.parametrize("table_visible", [True, False], ids=["org_sees_the_table", "org_mode_hides_the_table"])
def test_compile_hogql_predicate_against_flag_evaluations_reads_its_own_columns(
    team, materialized_browser, table_visible
):
    request = _flag_call_request(team, "properties.$browser = 'Chrome'")
    events_sql, _ = compile_hogql_predicate(request)

    with patch(
        "products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=table_visible
    ):
        flag_sql, values = compile_hogql_predicate(request, hogql_table=FLAG_EVALUATIONS_HOGQL_TABLE)

    assert "mat_$browser" in events_sql
    assert "mat_$browser" not in flag_sql
    assert "Chrome" in values.values()


@pytest.mark.parametrize(
    "predicate, error_match",
    [
        ("person_id = '5f1c9e2a-0b7d-4e63-9a48-2c3d1e7f6b90'", "join"),
        ("person.id = '5f1c9e2a-0b7d-4e63-9a48-2c3d1e7f6b90'", "join"),
        # Exposing elements_chain as '' on flag_evaluations would make this match every row.
        ("NOT elements_chain ILIKE '%checkout%'", "elements_chain"),
        ("properties.plan = 'pro'", "property-group map"),
        ("properties.`$feature/beta` = 'true'", "property-group map"),
        # Events reads a non-$ person property from person_properties_map_custom.
        ("person.properties.email = 'a@example.com'", "person_properties_map_custom"),
        # mat_$browser reads a stored "" as NULL, and the raw JSON read on flag_evaluations reads it as "".
        ("properties.$browser = ''", "materialized column mat_$browser"),
        ("properties.$browser IS NULL", "materialized column mat_$browser"),
        # The built-in $group_0 column scrubs the same way, with no mat_ prefix.
        ("properties.$group_0 IS NULL", "materialized column $group_0"),
        # A team's READY dynamic slot makes events read dmat_string_0, which the column registry does not list.
        ("properties.plan IS NULL", "materialized column dmat_string_0"),
    ],
    ids=[
        "person_id",
        "person_id_through_person",
        "elements_chain",
        "custom_property",
        "feature_flag_property",
        "custom_person_property",
        "materialized_property_equals_empty_string",
        "materialized_property_is_null",
        "builtin_group_column_is_null",
        "dynamic_slot_is_null",
    ],
)
def test_uncopied_rows_predicate_refuses_what_flag_evaluations_rows_cannot_answer(
    team, request, predicate, error_match
):
    if "$browser" in predicate:
        request.getfixturevalue("materialized_browser")
    if predicate == "properties.plan IS NULL":
        request.getfixturevalue("dmat_slot_for_plan")
    uncopied = uncopied_rows_predicate(_flag_call_request(team, predicate), FLAG_EVALUATIONS)

    assert uncopied.compiled is None
    assert error_match in uncopied.error


# A missing key, a JSON null and an escaped quote are the rows where two ways of reading a property can
# disagree.
_PARITY_ROW_PROPERTIES = [
    '{"$plan": "pro"}',
    '{"$plan": "free"}',
    '{"$plan": ""}',
    '{"$plan": null}',
    "{}",
    '{"$plan": "a\\"b"}',
    '{"$plan": 5}',
    '{"$plan": true}',
]


def _matches_by_row(read_table: str, team_id: int, fragment: str, values: dict) -> dict[str, bool]:
    rows = sync_execute(
        f"SELECT properties, ({fragment}) FROM {read_table} WHERE team_id = %(team_id)s",
        {**values, "team_id": team_id},
    )
    return {properties: bool(matched) for properties, matched in rows}


@pytest.mark.parametrize(
    "property_type, predicate",
    [
        pytest.param(None, "properties.$plan = 'pro'", id="equals"),
        pytest.param(None, "properties.$plan = ''", id="equals_empty_string"),
        pytest.param(None, "properties.$plan = 'a\"b'", id="equals_escaped_quote"),
        pytest.param(None, "properties.$plan != 'pro'", id="not_equals"),
        pytest.param(None, "properties.$plan IN ('pro', 'team')", id="in"),
        pytest.param(None, "properties.$plan > 'free'", id="greater"),
        pytest.param(None, "properties.$plan IS NULL", id="is_null"),
        pytest.param(None, "properties.$plan LIKE 'pr%'", id="like"),
        pytest.param("Numeric", "properties.$plan > 1", id="numeric_greater"),
        pytest.param("Boolean", "properties.$plan = true", id="boolean_equals"),
        pytest.param(None, "person.properties.$plan = 'pro'", id="person_property_equals"),
    ],
)
def test_flag_evaluations_predicate_matches_the_rows_the_events_predicate_matches(team, property_type, predicate):
    if property_type is not None:
        PropertyDefinition.objects.create(
            team=team, name="$plan", type=PropertyDefinition.Type.EVENT, property_type=property_type
        )
    request = _flag_call_request(team, predicate)
    events_sql, events_values = compile_hogql_predicate(request)
    assert "properties_group_" not in events_sql
    flag_sql, flag_values = compile_hogql_predicate(request, hogql_table=FLAG_EVALUATIONS_HOGQL_TABLE)

    now = timezone.now()
    rows = [(team.id, FLAG_EVALUATIONS_SOURCE_EVENT, uuid_lib.uuid4(), now, p, p) for p in _PARITY_ROW_PROPERTIES]
    columns = "(team_id, event, uuid, timestamp, properties, person_properties)"
    sync_execute(f"INSERT INTO writable_events {columns} VALUES", rows)
    sync_execute(f"INSERT INTO writable_flag_evaluations {columns} VALUES", rows)

    events_matches = _matches_by_row("events", team.id, events_sql, events_values)
    assert events_matches.keys() == set(_PARITY_ROW_PROPERTIES)
    assert _matches_by_row("flag_evaluations", team.id, flag_sql, flag_values) == events_matches


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


def test_property_presence_where_scopes_and_matches_property_columns(team):
    from posthog.clickhouse.client.escape import substitute_params_for_display

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=["$ip"],
            person_properties=["email"],
            start_time=datetime(2026, 4, 1),
            end_time=datetime(2026, 4, 15),
        )
    )
    predicate, params = ddr._property_presence_where(request)
    rendered = substitute_params_for_display(predicate, params)

    assert f"team_id = {team.id}" in rendered
    assert "timestamp >= '2026-04-01 00:00:00'" in rendered
    assert "timestamp < '2026-04-15 00:00:00'" in rendered
    assert "JSONHas(properties, '$ip')" in rendered
    assert "JSONHas(person_properties, 'email')" in rendered
    assert "%(" not in rendered


def test_property_presence_where_includes_materialized_columns(team):
    from posthog.clickhouse.client.escape import substitute_params_for_display

    request = DataDeletionRequest(
        **_base_kwargs(
            team_id=team.id,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=["$ip"],
            start_time=datetime(2026, 4, 1),
            end_time=datetime(2026, 4, 15),
        )
    )
    predicate, params = ddr._property_presence_where(request, mat_cols=[("mat_$ip", False)])
    rendered = substitute_params_for_display(predicate, params)

    assert "JSONHas(properties, '$ip')" in rendered
    assert "`mat_$ip` != ''" in rendered


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


def test_person_removal_rejects_both_selectors():
    request = DataDeletionRequest(**_person_kwargs(person_uuids=[str(uuid_lib.uuid4())], person_distinct_ids=["did-1"]))
    with pytest.raises(ValidationError, match="not both"):
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
        events=["$pageview"],
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


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"hogql_query": ""}, "Provide a HogQL query"),
        ({"execution_mode": ddr.ExecutionMode.IMMEDIATE}, "must use deferred execution"),
        ({"events": ["$pageview"]}, "cannot use legacy event filters"),
        ({"hogql_predicate": "event = '$pageview'"}, "cannot use legacy criteria"),
        ({"person_distinct_ids": ["person-1"]}, "only valid for person_removal"),
    ],
)
def test_hogql_event_removal_rejects_invalid_criteria(overrides: dict[str, object], match: str) -> None:
    fields = {
        "team_id": TEAM_ID,
        "request_type": RequestType.HOGQL_EVENT_REMOVAL,
        "execution_mode": ddr.ExecutionMode.DEFERRED,
        "hogql_query": "SELECT uuid FROM events",
    }
    fields.update(overrides)
    request = DataDeletionRequest(**fields)

    with pytest.raises(ValidationError, match=match):
        request.clean()


def test_hogql_event_removal_clean_passes() -> None:
    request = DataDeletionRequest(
        team_id=TEAM_ID,
        request_type=RequestType.HOGQL_EVENT_REMOVAL,
        execution_mode=ddr.ExecutionMode.DEFERRED,
        hogql_query="SELECT uuid FROM events WHERE event = {event_name}",
        hogql_variables={"event_name": {"kind": "HogQLVariable", "value": "$pageview"}},
    )

    request.clean()


@pytest.mark.parametrize(
    "request_type", [RequestType.EVENT_REMOVAL, RequestType.PROPERTY_REMOVAL, RequestType.PERSON_REMOVAL]
)
def test_legacy_request_types_reject_hogql_query_snapshot(request_type: str) -> None:
    if request_type == RequestType.EVENT_REMOVAL:
        fields = _base_kwargs(events=["$pageview"])
    elif request_type == RequestType.PROPERTY_REMOVAL:
        fields = _property_kwargs()
    else:
        fields = _person_kwargs()
    request = DataDeletionRequest(**fields, hogql_query="SELECT uuid FROM events")

    with pytest.raises(ValidationError, match="only valid for query-backed event removal"):
        request.clean()


def test_team_id_immutable_after_creation():
    request = DataDeletionRequest(**_base_kwargs(events=["$pageview"]))
    request._loaded_team_id = request.team_id  # simulate a row loaded from the DB
    request.team_id = TEAM_ID + 1
    with pytest.raises(ValidationError, match="team_id cannot be changed"):
        request.clean()


def test_team_id_unchanged_allows_other_edits():
    request = DataDeletionRequest(**_base_kwargs(events=["$pageview"]))
    request._loaded_team_id = request.team_id
    request.events = ["$pageview", "$autocapture"]
    request.clean()  # team_id unchanged → no raise


@override_settings(CACHES=LOCMEM_CACHE)
def test_cached_compile_hogql_predicate_reuses_cache_on_repeat():
    from django.core.cache import cache

    cache.clear()
    request = DataDeletionRequest(
        **_base_kwargs(events=["$pageview"], hogql_predicate="properties.$browser = 'Chrome'")
    )
    calls, fake_compile = _recording_compile()

    with patch.object(ddr, "compile_hogql_predicate", side_effect=fake_compile):
        assert cached_compile_hogql_predicate(request) == ("equals(1, 1)", {"k": "v"})
        # Second call for the same predicate is served from cache — no recompile.
        assert cached_compile_hogql_predicate(request) == ("equals(1, 1)", {"k": "v"})
        assert len(calls) == 1


@override_settings(CACHES=LOCMEM_CACHE)
def test_cached_compile_hogql_predicate_recompiles_when_predicate_text_changes():
    from django.core.cache import cache

    cache.clear()
    request = DataDeletionRequest(
        **_base_kwargs(events=["$pageview"], hogql_predicate="properties.$browser = 'Chrome'")
    )
    calls, fake_compile = _recording_compile()

    with patch.object(ddr, "compile_hogql_predicate", side_effect=fake_compile):
        cached_compile_hogql_predicate(request)
        # Changing the predicate text recompiles via the source guard, even without explicit clear.
        request.hogql_predicate = "properties.$browser = 'Firefox'"
        cached_compile_hogql_predicate(request)
        assert len(calls) == 2


@override_settings(CACHES=LOCMEM_CACHE)
def test_cached_compile_hogql_predicate_recompiles_after_explicit_invalidation():
    from django.core.cache import cache

    cache.clear()
    request = DataDeletionRequest(
        **_base_kwargs(events=["$pageview"], hogql_predicate="properties.$browser = 'Chrome'")
    )
    calls, fake_compile = _recording_compile()

    with patch.object(ddr, "compile_hogql_predicate", side_effect=fake_compile):
        cached_compile_hogql_predicate(request)
        # Explicit invalidation forces a recompile on the next call.
        invalidate_compiled_predicate_cache(request.pk)
        cached_compile_hogql_predicate(request)
        assert len(calls) == 2


@override_settings(CACHES=LOCMEM_CACHE)
def test_cached_compile_hogql_predicate_blank_predicate_skips_compile():
    request = DataDeletionRequest(**_base_kwargs(events=["$pageview"], hogql_predicate=""))
    with patch.object(ddr, "compile_hogql_predicate", side_effect=AssertionError("should not compile")):
        assert cached_compile_hogql_predicate(request) == ("", {})


@pytest.mark.django_db
def test_verify_queued_query_backed_request_counts_pending_queue_rows(team):
    request = DataDeletionRequest.objects.create(
        team_id=team.pk,
        request_type=RequestType.HOGQL_EVENT_REMOVAL,
        hogql_query="SELECT uuid FROM events",
        execution_mode="deferred",
        status=RequestStatus.QUEUED,
    )

    with patch("posthog.clickhouse.client.sync_execute", side_effect=[[[1]], [[0]]]) as execute:
        pending = ddr.verify_queued_request(request)
        completed = ddr.verify_queued_request(request)

    assert pending == ddr.VerifyOutcome(remaining=1, promoted=False)
    assert completed == ddr.VerifyOutcome(remaining=0, promoted=True)
    request.refresh_from_db()
    assert request.status == RequestStatus.COMPLETED
    query, params = execute.call_args_list[0].args
    assert "adhoc_events_deletion FINAL" in query
    assert params == {"team_id": team.pk, "request_id": str(request.pk)}


def test_query_backed_deletion_stats_are_rejected():
    request = DataDeletionRequest(
        team_id=TEAM_ID,
        request_type=RequestType.HOGQL_EVENT_REMOVAL,
        hogql_query="SELECT uuid FROM events",
        execution_mode="deferred",
    )

    with pytest.raises(ValueError, match="Stats are not available"):
        ddr.fetch_deletion_stats(request)


@time_machine.travel("2026-06-17T12:00:00Z", tick=False)
@pytest.mark.parametrize("start_days_ago,end_days_ago", [(15, 0), (400, 300), (400, 0), (15, -27_000)])
def test_copy_check_windows_tile_the_request_range(start_days_ago: int, end_days_ago: int) -> None:
    now = timezone.now()
    horizon = ddr._ttl_horizon(FLAG_EVALUATIONS)
    assert horizon is not None
    request = DataDeletionRequest(
        team_id=TEAM_ID,
        start_time=now - timedelta(days=start_days_ago),
        end_time=now - timedelta(days=end_days_ago),
    )

    windows = [
        (params["start_time"], params["end_time"])
        for _, params in ddr.rows_without_events_copy_criteria(request, FLAG_EVALUATIONS)
    ]

    assert windows[0][0] == request.start_time
    assert windows[-1][1] == request.end_time
    assert all(end == next_start for (_, end), (next_start, _) in pairwise(windows))
    # Only a window before the TTL horizon or after now may span more than 7 days.
    assert all(end - start <= timedelta(days=7) for start, end in windows if end > horizon and start < now)
    assert len(windows) <= 20


@time_machine.travel("2026-06-17T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "overrides,expected_fragment",
    [
        ({}, None),
        ({"request_type": RequestType.PROPERTY_REMOVAL}, "event removal"),
        ({"request_type": RequestType.PERSON_REMOVAL}, "event removal"),
        ({"end_time": None}, "has not closed"),
        # An open range keeps matching newly ingested events, so a count taken now can't bound what
        # the deferred drain deletes when it runs later.
        ({"end_time": datetime(2026, 6, 18, tzinfo=UTC)}, "has not closed"),
        ({"count": None}, "no matching event count"),
        ({"count": 100_000}, "at or above"),
        ({"count": 200_000}, "at or above"),
    ],
)
def test_auto_approve_blocker(overrides, expected_fragment):
    fields = {
        "team_id": TEAM_ID,
        "request_type": RequestType.EVENT_REMOVAL,
        "events": ["$pageview"],
        "start_time": datetime(2026, 6, 10, tzinfo=UTC),
        "end_time": datetime(2026, 6, 16, tzinfo=UTC),
        "status": RequestStatus.PENDING,
        "count": 1_000,
        **overrides,
    }
    blocker = auto_approve_blocker(DataDeletionRequest(**fields))
    if expected_fragment is None:
        assert blocker is None
    else:
        assert blocker is not None
        assert expected_fragment in blocker


def test_refresh_deletion_stats_does_not_write_over_a_concurrent_criteria_edit(team):
    request = DataDeletionRequest.objects.create(
        team_id=team.id,
        request_type=RequestType.EVENT_REMOVAL,
        events=["$pageview"],
        start_time=datetime(2026, 6, 10, tzinfo=UTC),
        end_time=datetime(2026, 6, 16, tzinfo=UTC),
        status=RequestStatus.PENDING,
    )
    stale = DataDeletionRequest.objects.get(pk=request.pk)
    # Another operator broadens the criteria while the count is running. Saving that clears the stats,
    # because the numbers no longer describe the request.
    DataDeletionRequest.objects.filter(pk=request.pk).update(
        delete_all_events=True,
        events=[],
        count=None,
        stats_calculated_at=None,
        status=RequestStatus.DRAFT,
        updated_at=timezone.now(),
    )
    counted = {
        "count": 42,
        "part_count": 1,
        "parts_size": 1,
        "parts_row_count": 42,
        "min_timestamp": None,
        "max_timestamp": None,
    }

    with patch.object(ddr, "fetch_deletion_stats", return_value=counted):
        with pytest.raises(ddr.StaleDeletionRequestError):
            ddr.refresh_deletion_stats(stale)

    request.refresh_from_db()
    assert request.count is None
    assert request.stats_calculated_at is None
