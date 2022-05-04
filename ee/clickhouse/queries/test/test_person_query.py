import pytest

from ee.clickhouse.materialized_columns import materialize
from posthog.client import sync_execute
from posthog.models.filters import Filter
from posthog.models.team import Team
from posthog.queries.person_query import PersonQuery
from posthog.test.base import _create_person


def person_query(team: Team, filter: Filter, **kwargs):
    return PersonQuery(filter, team.pk, **kwargs).get_query()[0]


def run_query(team: Team, filter: Filter, **kwargs):
    query, params = PersonQuery(filter, team.pk, **kwargs).get_query()
    rows = sync_execute(query, {**params, "team_id": team.pk})

    if len(rows) > 0:
        return {"rows": len(rows), "columns": len(rows[0])}
    else:
        return {"rows": 0}


@pytest.fixture
def testdata(db, team):
    materialize("person", "email")
    _create_person(
        distinct_ids=["1"],
        team_id=team.pk,
        properties={"email": "tim@posthog.com", "$os": "windows", "$browser": "chrome"},
    )
    _create_person(
        distinct_ids=["2"],
        team_id=team.pk,
        properties={"email": "marius@posthog.com", "$os": "Mac", "$browser": "firefox"},
    )
    _create_person(
        distinct_ids=["3"],
        team_id=team.pk,
        properties={"email": "karl@example.com", "$os": "windows", "$browser": "mozilla"},
    )


def test_person_query(testdata, team, snapshot):
    filter = Filter(data={"properties": []})

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 3, "columns": 1}

    filter = Filter(
        data={
            "properties": [
                {"key": "event_prop", "value": "value"},
                {"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},
            ],
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 1}


def test_person_query_with_anded_property_groups(testdata, team, snapshot):
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {"key": "event_prop", "value": "value"},
                    {"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},
                    {"key": "$os", "type": "person", "value": "windows", "operator": "exact"},
                    {"key": "$browser", "type": "person", "value": "chrome", "operator": "exact"},
                ],
            },
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 1, "columns": 1}


def test_person_query_with_and_and_or_property_groups(testdata, team, snapshot):
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},
                            {"key": "$browser", "type": "person", "value": "karl", "operator": "icontains"},
                        ],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {"key": "event_prop", "value": "value"},
                            {
                                "key": "$os",
                                "type": "person",
                                "value": "windows",
                                "operator": "exact",
                            },  # this can't be pushed down
                            # so person query should return only rows from the first OR group
                        ],
                    },
                ],
            },
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 2}


def test_person_query_with_extra_requested_fields(testdata, team, snapshot):
    filter = Filter(
        data={
            "properties": [{"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},],
            "breakdown": "person_prop_4326",
            "breakdown_type": "person",
        },
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 2}

    filter = filter.with_data({"breakdown": "email", "breakdown_type": "person"})
    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 2}


def test_person_query_with_entity_filters(testdata, team, snapshot):
    filter = Filter(
        data={
            "events": [
                {
                    "id": "$pageview",
                    "properties": [{"key": "email", "type": "person", "value": "karl", "operator": "icontains"}],
                }
            ]
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 3, "columns": 2}

    assert person_query(team, filter, entity=filter.entities[0]) == snapshot
    assert run_query(team, filter, entity=filter.entities[0]) == {"rows": 1, "columns": 1}


def test_person_query_with_extra_fields(testdata, team, snapshot):
    filter = Filter(
        data={"properties": [{"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},]},
    )

    assert person_query(team, filter, extra_fields=["person_props", "pmat_email"]) == snapshot
    assert run_query(team, filter, extra_fields=["person_props", "pmat_email"]) == {"rows": 2, "columns": 3}


def test_person_query_with_entity_filters_and_property_group_filters(testdata, team, snapshot):
    filter = Filter(
        data={
            "events": [
                {
                    "id": "$pageview",
                    "properties": {
                        "type": "OR",
                        "values": [
                            {"key": "email", "type": "person", "value": "marius", "operator": "icontains"},
                            {"key": "$os", "type": "person", "value": "windows", "operator": "icontains"},
                        ],
                    },
                }
            ],
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},
                            {"key": "$browser", "type": "person", "value": "karl", "operator": "icontains"},
                        ],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {"key": "event_prop", "value": "value"},
                            {"key": "$os", "type": "person", "value": "windows", "operator": "exact"},
                        ],
                    },
                ],
            },
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 3}

    assert person_query(team, filter, entity=filter.entities[0]) == snapshot
    assert run_query(team, filter, entity=filter.entities[0]) == {"rows": 2, "columns": 2}
