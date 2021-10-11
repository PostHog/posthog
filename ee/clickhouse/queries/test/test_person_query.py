import pytest

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns import materialize
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.models.team import Team


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def person_query(team: Team, filter: Filter, **kwargs):
    return ClickhousePersonQuery(filter, team.pk, **kwargs).get_query()[0]


def run_query(team: Team, filter: Filter, **kwargs):
    query, params = ClickhousePersonQuery(filter, team.pk, **kwargs).get_query()
    rows = sync_execute(query, {**params, "team_id": team.pk})

    if len(rows) > 0:
        return {"rows": len(rows), "columns": len(rows[0])}
    else:
        return {"rows": 0}


@pytest.fixture
def testdata(db, team):
    materialize("person", "email")
    _create_person(distinct_ids=["1"], team_id=team.pk, properties={"email": "tim@posthog.com"})
    _create_person(distinct_ids=["2"], team_id=team.pk, properties={"email": "marius@posthog.com"})
    _create_person(distinct_ids=["3"], team_id=team.pk, properties={"email": "karl@example.com"})


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
