from typing import Dict, List
from uuid import UUID, uuid4

import pytest

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.property import parse_prop_clauses, prop_filter_json_extract
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.cohort import Cohort
from posthog.models.element import Element
from posthog.models.event import Event
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.test.base import BaseTest, TestMixin


def _create_event(**kwargs) -> UUID:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return pk


def _create_person(**kwargs) -> Person:
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestPropFormat(ClickhouseTestMixin, BaseTest):
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

        filter = Filter(data={"properties": [{"key": "attr", "value": "some_val"}],})
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_selector_tag_name(self):
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_other_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text="bla bla",
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(tag_name="button", attr_class=["btn", "btn-primary"], nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="label", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text="bla bla",
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(tag_name="button", attr_class=["btn", "btn-secondary"], nth_child=0, nth_of_type=0),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="img", nth_child=0, nth_of_type=0, attr_id="nested",),
            ],
        )

        # selector

        filter = Filter(
            data={"properties": [{"key": "selector", "value": [".btn"], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(
            data={"properties": [{"key": "selector", "value": ".btn", "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter)), 2)

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


class TestPropDenormalized(ClickhouseTestMixin, BaseTest):
    def _run_query(self, filter: Filter) -> List:
        query, params = parse_prop_clauses(filter.properties, self.team.pk, allow_denormalized_props=True)
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
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

        with self.settings(CLICKHOUSE_DENORMALIZED_PROPERTIES=["test_prop", "something_else"]):
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

            filter = Filter(
                data={"properties": [{"key": "test_prop", "value": "_other_", "operator": "not_icontains"}],}
            )
            self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_event_denormalized_ints(self):
        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 0},
        )

        _create_event(
            event="$pageview", team=self.team, distinct_id="whatever", properties={"test_prop": 2},
        )

        with self.settings(CLICKHOUSE_DENORMALIZED_PROPERTIES=["test_prop", "something_else"]):
            filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "gt"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "lt"}],})
            self.assertEqual(len(self._run_query(filter)), 1)

            filter = Filter(data={"properties": [{"key": "test_prop", "value": 0}],})
            self.assertEqual(len(self._run_query(filter)), 1)


@pytest.fixture
def test_events(db, team) -> List[UUID]:
    return [
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"email": "test@posthog.com"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"email": "mongo@example.com"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"attr": "some_val"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"attr": "50"},),
        _create_event(event="$pageview", team=team, distinct_id="whatever", properties={"attr": 5},),
    ]


@pytest.mark.parametrize(
    "property,expected_event_indexes",
    [
        (Property(key="email", value="test@posthog.com"), [0]),
        (Property(key="email", value="test@posthog.com", operator="exact"), [0]),
        (Property(key="email", value=["pineapple@pizza.com", "mongo@example.com"], operator="exact"), [1]),
        (Property(key="attr", value="5"), [4]),
        (Property(key="email", value="test@posthog.com", operator="is_not"), range(1, 5)),
        (Property(key="email", value=["test@posthog.com", "mongo@example.com"], operator="is_not"), range(2, 5)),
        (Property(key="email", value=r".*est@.*", operator="regex"), [0]),
        (Property(key="email", value=r"?.", operator="regex"), []),
    ],
)
def test_prop_filter_json_extract(test_events, property, expected_event_indexes):
    query, params = prop_filter_json_extract(property, 0)
    uuids = list(sorted([uuid for (uuid,) in sync_execute(f"SELECT uuid FROM events WHERE 1 = 1 {query}", params)]))
    expected = list(sorted([test_events[index] for index in expected_event_indexes]))

    assert uuids == expected
