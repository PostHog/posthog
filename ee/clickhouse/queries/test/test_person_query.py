import pytest
from posthog.test.base import _create_person

from posthog.clickhouse.client import sync_execute
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.queries.person_query import PersonQuery

from ee.clickhouse.materialized_columns.columns import materialize


def person_query(team: Team, filter: Filter, **kwargs):
    return PersonQuery(filter, team.pk, **kwargs).get_query()[0]


def run_query(team: Team, filter: Filter, **kwargs):
    query, params = PersonQuery(filter, team.pk, **kwargs).get_query()
    rows = sync_execute(query, {**params, **filter.hogql_context.values, "team_id": team.pk})
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
        properties={
            "email": "karl@example.com",
            "$os": "windows",
            "$browser": "mozilla",
        },
    )


def test_person_query(testdata, team, snapshot):
    filter = Filter(data={"properties": []})

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 3, "columns": 1}

    filter = Filter(
        data={
            "properties": [
                {"key": "event_prop", "value": "value"},
                {
                    "key": "email",
                    "type": "person",
                    "value": "posthog",
                    "operator": "icontains",
                },
            ]
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 1}


def test_person_query_with_multiple_cohorts(testdata, team, snapshot):
    filter = Filter(data={"properties": []})

    for i in range(10):
        _create_person(
            team_id=team.pk,
            distinct_ids=[f"person{i}"],
            properties={"group": str(i), "email": f"{i}@hey.com"},
        )

    cohort1 = Cohort.objects.create(
        team=team,
        filters={
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "group", "value": "none", "type": "person"},
                            {"key": "group", "value": ["1", "2", "3"], "type": "person"},
                        ],
                    }
                ],
            }
        },
        name="cohort1",
    )

    cohort2 = Cohort.objects.create(
        team=team,
        filters={
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "group",
                                "value": ["1", "2", "3", "4", "5", "6"],
                                "type": "person",
                            },
                        ],
                    }
                ],
            }
        },
        name="cohort2",
    )

    cohort1.calculate_people_ch(pending_version=0)
    cohort2.calculate_people_ch(pending_version=0)

    cohort_filters = [
        Property(key="id", type="cohort", value=cohort1.pk),
        Property(key="id", type="cohort", value=cohort2.pk),
    ]

    filter = Filter(
        data={
            "properties": [
                {
                    "key": "email",
                    "type": "person",
                    "value": "posthog",
                    "operator": "icontains",
                },
            ]
        }
    )

    filter2 = Filter(
        data={
            "properties": [
                {
                    "key": "email",
                    "type": "person",
                    "value": "hey",
                    "operator": "icontains",
                },
            ]
        }
    )

    assert run_query(team, filter) == {"rows": 2, "columns": 1}

    # 3 rows because the intersection between cohorts 1 and 2 is person1, person2, and person3,
    # with their respective group properties
    assert run_query(team, filter2, cohort_filters=cohort_filters) == {
        "rows": 3,
        "columns": 1,
    }
    assert person_query(team, filter2, cohort_filters=cohort_filters) == snapshot


def test_person_query_with_anded_property_groups(testdata, team, snapshot):
    filter = Filter(
        data={
            "properties": {
                "type": "AND",
                "values": [
                    {"key": "event_prop", "value": "value"},
                    {
                        "key": "email",
                        "type": "person",
                        "value": "posthog",
                        "operator": "icontains",
                    },
                    {
                        "key": "$os",
                        "type": "person",
                        "value": "windows",
                        "operator": "exact",
                    },
                    {
                        "key": "$browser",
                        "type": "person",
                        "value": "chrome",
                        "operator": "exact",
                    },
                ],
            }
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
                            {
                                "key": "email",
                                "type": "person",
                                "value": "posthog",
                                "operator": "icontains",
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "value": "karl",
                                "operator": "icontains",
                            },
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
            }
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 2}


def test_person_query_with_extra_requested_fields(testdata, team, snapshot):
    filter = Filter(
        data={
            "properties": [
                {
                    "key": "email",
                    "type": "person",
                    "value": "posthog",
                    "operator": "icontains",
                }
            ],
            "breakdown": "person_prop_4326",
            "breakdown_type": "person",
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 2}

    filter = filter.shallow_clone({"breakdown": "email", "breakdown_type": "person"})
    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 2}


def test_person_query_with_entity_filters(testdata, team, snapshot):
    filter = Filter(
        data={
            "events": [
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "karl",
                            "operator": "icontains",
                        }
                    ],
                }
            ]
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 3, "columns": 2}

    assert person_query(team, filter, entity=filter.entities[0]) == snapshot
    assert run_query(team, filter, entity=filter.entities[0]) == {
        "rows": 1,
        "columns": 1,
    }


def test_person_query_with_extra_fields(testdata, team, snapshot):
    filter = Filter(
        data={
            "properties": [
                {
                    "key": "email",
                    "type": "person",
                    "value": "posthog",
                    "operator": "icontains",
                }
            ]
        }
    )

    assert person_query(team, filter, extra_fields=["person_props", "pmat_email"]) == snapshot
    assert run_query(team, filter, extra_fields=["person_props", "pmat_email"]) == {
        "rows": 2,
        "columns": 3,
    }


def test_person_query_with_entity_filters_and_property_group_filters(testdata, team, snapshot):
    filter = Filter(
        data={
            "events": [
                {
                    "id": "$pageview",
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "marius",
                                "operator": "icontains",
                            },
                            {
                                "key": "$os",
                                "type": "person",
                                "value": "windows",
                                "operator": "icontains",
                            },
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
                            {
                                "key": "email",
                                "type": "person",
                                "value": "posthog",
                                "operator": "icontains",
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "value": "karl",
                                "operator": "icontains",
                            },
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
                            },
                        ],
                    },
                ],
            },
        }
    )

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 2, "columns": 3}

    assert person_query(team, filter, entity=filter.entities[0]) == snapshot
    assert run_query(team, filter, entity=filter.entities[0]) == {
        "rows": 2,
        "columns": 2,
    }


def test_person_query_with_updated_after(testdata, team, snapshot):
    filter = Filter(data={"updated_after": "2023-04-04"})

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 3, "columns": 1}

    filter = Filter(data={"updated_after": "2055-04-04"})

    assert person_query(team, filter) == snapshot
    assert run_query(team, filter) == {"rows": 0}
