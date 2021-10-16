from typing import List
from uuid import UUID, uuid4

import pytest

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import materialize
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.property import parse_prop_clauses, prop_filter_json_extract
from ee.clickhouse.models.util import PersonPropertiesMode
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.element import Element
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.models.property import Property
from posthog.test.base import BaseTest


def _create_event(**kwargs) -> UUID:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return pk


def _create_person(**kwargs) -> Person:
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestPropFormat(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _run_query(self, filter: Filter) -> List:
        query, params = parse_prop_clauses(filter.properties, self.team.pk, allow_denormalized_props=True)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        return sync_execute(final_query, {**params, "team_id": self.team.pk})

    def test_prop_person(self):

        _create_person(
            distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"email": "another@posthog.com"}
        )

        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"email": "test@posthog.com"})

        _create_event(
            event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"},
        )

        filter = Filter(data={"properties": [{"key": "email", "value": "test@posthog.com", "type": "person"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_event(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"attr": "some_other_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"attr": "some_val"},
        )

        filter_exact = Filter(data={"properties": [{"key": "attr", "value": "some_val"}],})
        self.assertEqual(len(self._run_query(filter_exact)), 1)

        filter_regex = Filter(data={"properties": [{"key": "attr", "value": "some_.+_val", "operator": "regex"}],})
        self.assertEqual(len(self._run_query(filter_regex)), 1)

        filter_icontains = Filter(data={"properties": [{"key": "attr", "value": "Some_Val", "operator": "icontains"}],})
        self.assertEqual(len(self._run_query(filter_icontains)), 1)

        filter_not_icontains = Filter(
            data={"properties": [{"key": "attr", "value": "other", "operator": "not_icontains"}],}
        )
        self.assertEqual(len(self._run_query(filter_not_icontains)), 1)

    def test_prop_element(self):
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_other_val"},
            elements=[
                Element(tag_name="a", href="/a-url", attr_class=["small"], text="bla bla", nth_child=1, nth_of_type=0,),
                Element(tag_name="button", attr_class=["btn", "btn-primary"], nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="label", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text='bla"bla',
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(tag_name="button", attr_class=["btn", "btn-secondary"], nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="img", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", href="/789", nth_child=0, nth_of_type=0,),
                Element(tag_name="button", attr_class=["btn", "btn-tertiary"], nth_child=0, nth_of_type=0),
            ],
        )

        # selector

        filter = Filter(
            data={"properties": [{"key": "selector", "value": [".btn"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 3)

        filter = Filter(
            data={"properties": [{"key": "selector", "value": ".btn", "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 3)

        filter = Filter(
            data={
                "properties": [{"key": "selector", "value": [".btn-primary"], "operator": "exact", "type": "element"}]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [{"key": "selector", "value": [".btn-secondary"], "operator": "exact", "type": "element"}]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [".btn-primary", ".btn-secondary"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter_selector_exact_empty = Filter(
            data={"properties": [{"key": "selector", "value": [], "operator": "exact", "type": "element",}]}
        )
        self.assertEqual(len(self._run_query(filter_selector_exact_empty)), 0)

        filter_selector_is_not_empty = Filter(
            data={"properties": [{"key": "selector", "value": [], "operator": "is_not", "type": "element",}]}
        )
        self.assertEqual(len(self._run_query(filter_selector_is_not_empty)), 3)

        # tag_name

        filter = Filter(
            data={"properties": [{"key": "tag_name", "value": ["div"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(
            data={"properties": [{"key": "tag_name", "value": "div", "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(
            data={"properties": [{"key": "tag_name", "value": ["img"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={"properties": [{"key": "tag_name", "value": ["label"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [{"key": "tag_name", "value": ["img", "label"], "operator": "exact", "type": "element"}]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        # href/text

        filter_href_exact = Filter(
            data={"properties": [{"key": "href", "value": ["/a-url"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_exact)), 2)

        filter_href_exact_double = Filter(
            data={"properties": [{"key": "href", "value": ["/a-url", "/789"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_exact_double)), 3)

        filter_href_exact_empty = Filter(
            data={"properties": [{"key": "href", "value": [], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_exact_empty)), 0)

        filter_href_is_not = Filter(
            data={"properties": [{"key": "href", "value": ["/a-url"], "operator": "is_not", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_is_not)), 1)

        filter_href_is_not_double = Filter(
            data={"properties": [{"key": "href", "value": ["/a-url", "/789"], "operator": "is_not", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_is_not_double)), 0)

        filter_href_is_not_empty = Filter(
            data={"properties": [{"key": "href", "value": [], "operator": "is_not", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_is_not_empty)), 3)

        filter_href_exact_with_tag_name_is_not = Filter(
            data={
                "properties": [
                    {"key": "href", "value": ["/a-url"], "type": "element"},
                    {"key": "tag_name", "value": ["marquee"], "operator": "is_not", "type": "element"},
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_exact_with_tag_name_is_not)), 2)

        filter_href_icontains = Filter(
            data={"properties": [{"key": "href", "value": ["UrL"], "operator": "icontains", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_icontains)), 2)

        filter_href_regex = Filter(
            data={"properties": [{"key": "href", "value": "/a-.+", "operator": "regex", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_regex)), 2)

        filter_href_not_regex = Filter(
            data={"properties": [{"key": "href", "value": r"/\d+", "operator": "not_regex", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_not_regex)), 2)

        filter_text_icontains_with_doublequote = Filter(
            data={"properties": [{"key": "text", "value": 'bla"bla', "operator": "icontains", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_text_icontains_with_doublequote)), 1)

        filter_text_is_set = Filter(
            data={"properties": [{"key": "text", "value": "is_set", "operator": "is_set", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_text_is_set)), 2)

        filter_text_is_not_set = Filter(
            data={"properties": [{"key": "text", "value": "is_not_set", "operator": "is_not_set", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_text_is_not_set)), 1)

    def test_prop_ints_saved_as_strings(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "0"},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "2"},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 2},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "string"},
        )
        filter = Filter(data={"properties": [{"key": "test_prop", "value": "2"}],})
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 2}],})
        self.assertEqual(len(self._run_query(filter)), 2)

        # value passed as string
        filter = Filter(data={"properties": [{"key": "test_prop", "value": "1", "operator": "gt"}],})
        self.assertEqual(len(self._run_query(filter)), 2)
        filter = Filter(data={"properties": [{"key": "test_prop", "value": "3", "operator": "lt"}],})
        self.assertEqual(len(self._run_query(filter)), 3)

        # value passed as int
        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "gt"}],})
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 3, "operator": "lt"}],})
        self.assertEqual(len(self._run_query(filter)), 3)

    def test_prop_decimals(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 1.4},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 1.3},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 2},
        )
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 2.5},
        )

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1.5}],})
        self.assertEqual(len(self._run_query(filter)), 0)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1.2, "operator": "gt"}],})
        self.assertEqual(len(self._run_query(filter)), 4)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "1.2", "operator": "gt"}],})
        self.assertEqual(len(self._run_query(filter)), 4)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 2.3, "operator": "lt"}],})
        self.assertEqual(len(self._run_query(filter)), 3)


class TestPropDenormalized(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _run_query(self, filter: Filter, join_person_tables=False) -> List:
        query, params = parse_prop_clauses(
            filter.properties,
            self.team.pk,
            allow_denormalized_props=True,
            person_properties_mode=PersonPropertiesMode.EXCLUDE,
        )
        joins = ""
        if join_person_tables:
            person_query = ClickhousePersonQuery(filter, self.team.pk)
            person_subquery, person_join_params = person_query.get_query()
            joins = f"""
                INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi ON events.distinct_id = pdi.distinct_id
                INNER JOIN ({person_subquery}) person ON pdi.person_id = person.id
            """
            params.update(person_join_params)

        final_query = f"SELECT uuid FROM events {joins} WHERE team_id = %(team_id)s {query}"
        # Make sure we don't accidentally use json on the properties field
        self.assertNotIn("json", final_query.lower())
        return sync_execute(final_query, {**params, "team_id": self.team.pk})

    def test_prop_event_denormalized(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "some_other_val"},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": "some_val"},
        )

        materialize("events", "test_prop")
        materialize("events", "something_else")

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_not"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_set"}],})
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_not_set"}],})
        self.assertEqual(len(self._run_query(filter)), 0)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "_other_", "operator": "icontains"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "_other_", "operator": "not_icontains"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_person_denormalized(self):
        _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"email": "test@posthog.com"})
        _create_event(event="$pageview", team=self.team, distinct_id="some_id")

        materialize("person", "email")

        filter = Filter(
            data={"properties": [{"key": "email", "type": "person", "value": "posthog", "operator": "icontains"}],}
        )
        self.assertEqual(len(self._run_query(filter, join_person_tables=True)), 1)

        filter = Filter(
            data={"properties": [{"key": "email", "type": "person", "value": "posthog", "operator": "not_icontains"}],}
        )
        self.assertEqual(len(self._run_query(filter, join_person_tables=True)), 0)

    def test_prop_event_denormalized_ints(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 0},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 2},
        )

        materialize("events", "test_prop")
        materialize("events", "something_else")

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "gt"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "lt"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 0}],})
        self.assertEqual(len(self._run_query(filter)), 1)


def test_parse_prop_clauses_defaults(snapshot):
    filter = Filter(
        data={
            "properties": [
                {"key": "event_prop", "value": "value"},
                {"key": "email", "type": "person", "value": "posthog", "operator": "icontains"},
            ],
        }
    )

    assert parse_prop_clauses(filter.properties, None) == snapshot
    assert (
        parse_prop_clauses(
            filter.properties, None, person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN
        )
        == snapshot
    )
    assert parse_prop_clauses(filter.properties, None, person_properties_mode=PersonPropertiesMode.EXCLUDE) == snapshot


@pytest.fixture
def test_events(db, team) -> List[UUID]:
    return [
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"email": "test@posthog.com"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"email": "mongo@example.com"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"attr": "some_val"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"attr": "50"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"attr": 5},),
    ]


TEST_PROPERTIES = [
    (Property(key="email", value="test@posthog.com"), [0]),
    (Property(key="email", value="test@posthog.com", operator="exact"), [0]),
    (Property(key="email", value=["pineapple@pizza.com", "mongo@example.com"], operator="exact"), [1]),
    (Property(key="attr", value="5"), [4]),
    (Property(key="email", value="test@posthog.com", operator="is_not"), range(1, 5)),
    (Property(key="email", value=["test@posthog.com", "mongo@example.com"], operator="is_not"), range(2, 5)),
    (Property(key="email", value=r".*est@.*", operator="regex"), [0]),
    (Property(key="email", value=r"?.", operator="regex"), []),
    (Property(key="email", operator="is_set", value="is_set"), [0, 1]),
    (Property(key="email", operator="is_not_set", value="is_not_set"), range(2, 5)),
]


@pytest.mark.parametrize("property,expected_event_indexes", TEST_PROPERTIES)
def test_prop_filter_json_extract(test_events, property, expected_event_indexes, team):
    query, params = prop_filter_json_extract(property, 0, allow_denormalized_props=False)
    uuids = list(
        sorted(
            [
                uuid
                for (uuid,) in sync_execute(
                    f"SELECT uuid FROM events WHERE team_id = %(team_id)s {query}", {"team_id": team.pk, **params}
                )
            ]
        )
    )
    expected = list(sorted([test_events[index] for index in expected_event_indexes]))

    assert uuids == expected


@pytest.mark.parametrize("property,expected_event_indexes", TEST_PROPERTIES)
def test_prop_filter_json_extract_materialized(test_events, property, expected_event_indexes, team):
    materialize("events", "attr")
    materialize("events", "email")

    query, params = prop_filter_json_extract(property, 0, allow_denormalized_props=True)

    assert "JSONExtract" not in query

    uuids = list(
        sorted(
            [
                uuid
                for (uuid,) in sync_execute(
                    f"SELECT uuid FROM events WHERE team_id = %(team_id)s {query}", {"team_id": team.pk, **params}
                )
            ]
        )
    )
    expected = list(sorted([test_events[index] for index in expected_event_indexes]))

    assert uuids == expected
