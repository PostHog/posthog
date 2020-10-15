import json
from typing import Any, Callable, Optional

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone

from posthog.api.test.base import BaseTest
from posthog.models import Cohort, Element, Event, Filter, Person
from posthog.models.team import Team


class TestFilter(BaseTest):
    def test_old_style_properties(self):
        filter = Filter(data={"properties": {"$browser__is_not": "IE7", "$OS": "Mac",}})
        self.assertEqual(filter.properties[0].key, "$browser")
        self.assertEqual(filter.properties[0].operator, "is_not")
        self.assertEqual(filter.properties[0].value, "IE7")
        self.assertEqual(filter.properties[0].type, "event")
        self.assertEqual(filter.properties[1].key, "$OS")
        self.assertEqual(filter.properties[1].operator, None)
        self.assertEqual(filter.properties[1].value, "Mac")

    def test_to_dict(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}],
                "display": "ActionsLineGraph",
                "compare": True,
                "interval": "",
                "actions": [],
            }
        ).to_dict()
        self.assertEqual(list(filter.keys()), ["events", "display", "compare"])


class TestSelectors(BaseTest):
    def test_selectors(self):
        event1 = Event.objects.create(
            team=self.team,
            event="$autocapture",
            elements=[Element.objects.create(tag_name="a"), Element.objects.create(tag_name="div"),],
        )
        event2 = Event.objects.create(team=self.team, event="$autocapture")
        filter = Filter(data={"properties": [{"key": "selector", "value": "div > a", "type": "element"}]})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events.count(), 1)


def property_to_Q_test_factory(filter_events: Callable, event_factory, person_factory):
    class TestPropertiesToQ(BaseTest):
        def test_simple(self):
            event_factory(team=self.team, event="$pageview")
            event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
            )
            filter = Filter(data={"properties": {"$current_url": "https://whatever.com"}})
            events = filter_events(filter, self.team)
            self.assertEqual(events.count(), 1)

        def test_contains(self):
            event_factory(team=self.team, event="$pageview")
            event2 = event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
            )
            filter = Filter(data={"properties": {"$current_url__icontains": "whatever"}})
            events = filter_events(filter, self.team)
            self.assertEqual(events.get(), event2)

        def test_regex(self):
            event_factory(team=self.team, event="$pageview")
            event2 = event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
            )
            filter = Filter(data={"properties": {"$current_url__regex": "\.com$"}})
            events = filter_events(filter, self.team)
            self.assertEqual(events.get(), event2)

        def test_is_not(self):
            event1 = event_factory(team=self.team, event="$pageview")
            event2 = event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://something.com"},
            )
            event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
            )
            filter = Filter(data={"properties": {"$current_url__is_not": "https://whatever.com"}})
            events = filter_events(filter, self.team)
            self.assertEqual(events[0], event1)
            self.assertEqual(events[1], event2)
            self.assertEqual(len(events), 2)

        def test_does_not_contain(self):
            event1 = event_factory(team=self.team, event="$pageview")
            event2 = event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://something.com"},
            )
            event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
            )
            event3 = event_factory(team=self.team, event="$pageview", properties={"$current_url": None},)
            filter = Filter(data={"properties": {"$current_url__not_icontains": "whatever.com"}})
            events = filter_events(filter, self.team, order_by="id")
            self.assertEqual(events[0], event1)
            self.assertEqual(events[1], event2)
            self.assertEqual(events[2], event3)
            self.assertEqual(len(events), 3)

        def test_multiple(self):
            event2 = event_factory(
                team=self.team,
                event="$pageview",
                properties={"$current_url": "https://something.com", "another_key": "value",},
            )
            event_factory(
                team=self.team, event="$pageview", properties={"$current_url": "https://something.com"},
            )
            filter = Filter(data={"properties": {"$current_url__icontains": "something.com", "another_key": "value",}})
            events = filter_events(filter, self.team)
            self.assertEqual(events[0], event2)
            self.assertEqual(len(events), 1)

        def test_user_properties(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"group": 1})
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"group": 2})
            event2 = event_factory(
                team=self.team,
                distinct_id="person1",
                event="$pageview",
                properties={"$current_url": "https://something.com", "another_key": "value",},
            )
            event_factory(
                team=self.team,
                distinct_id="person2",
                event="$pageview",
                properties={"$current_url": "https://something.com"},
            )
            filter = Filter(data={"properties": [{"key": "group", "value": 1, "type": "person"}]})
            events = filter_events(filter=filter, team=self.team, person_query=True, order_by=None)
            self.assertEqual(events[0], event2)
            self.assertEqual(len(events), 1)

        def test_person_cohort_properties(self):
            person1_distinct_id = "person1"
            person1 = Person.objects.create(team=self.team, distinct_ids=[person1_distinct_id], properties={"group": 1})
            cohort1 = Cohort.objects.create(team=self.team, groups={}, name="cohort1")
            cohort1.people.add(person1)

            filters = {"cohort": [{"key": "1", "value": "true"}]}

            matched_person = (
                Person.objects.filter(team_id=self.team.pk, persondistinctid__distinct_id=person1_distinct_id)
                .filter(Filter(data=filters).properties_to_Q(team_id=self.team.pk, is_person_query=True))
                .exists()
            )
            self.assertTrue(matched_person)

        def test_boolean_filters(self):
            event1 = event_factory(team=self.team, event="$pageview")
            event2 = event_factory(team=self.team, event="$pageview", properties={"is_first_user": True})
            filter = Filter(data={"properties": [{"key": "is_first_user", "value": "true"}]})
            events = filter_events(filter, self.team)
            self.assertEqual(events[0], event2)
            self.assertEqual(len(events), 1)

        def test_is_not_set_and_is_set(self):
            event1 = event_factory(team=self.team, event="$pageview")
            event2 = event_factory(team=self.team, event="$pageview", properties={"is_first_user": True})
            filter = Filter(
                data={"properties": [{"key": "is_first_user", "operator": "is_not_set", "value": "is_not_set",}]}
            )
            events = filter_events(filter, self.team)
            self.assertEqual(events[0], event1)
            self.assertEqual(len(events), 1)

            filter = Filter(data={"properties": [{"key": "is_first_user", "operator": "is_set", "value": "is_set"}]})
            events = filter_events(filter, self.team)

        def test_json_object(self):
            person1 = person_factory(
                team_id=self.team.pk,
                distinct_ids=["person1"],
                properties={"name": {"first_name": "Mary", "last_name": "Smith"}},
            )
            event1 = event_factory(
                team=self.team,
                distinct_id="person1",
                event="$pageview",
                properties={"$current_url": "https://something.com"},
            )
            filter = Filter(
                data={
                    "properties": [
                        {
                            "key": "name",
                            "value": json.dumps({"first_name": "Mary", "last_name": "Smith"}),
                            "type": "person",
                        }
                    ]
                }
            )
            events = filter_events(filter=filter, team=self.team, person_query=True, order_by=None)
            self.assertEqual(events[0], event1)
            self.assertEqual(len(events), 1)

    return TestPropertiesToQ


def _filter_events(filter: Filter, team: Team, person_query: Optional[bool] = False, order_by: Optional[str] = None):
    events = Event.objects

    if person_query:
        events = events.add_person_id(team.pk)

    events = events.filter(filter.properties_to_Q(team_id=team.pk))
    if order_by:
        events = events.order_by(order_by)
    return events


class TestDjangoPropertiesToQ(property_to_Q_test_factory(_filter_events, Event.objects.create, Person.objects.create)):  # type: ignore
    pass


class TestDateFilterQ(BaseTest):
    def test_filter_by_all(self):
        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "name",
                        "value": json.dumps({"first_name": "Mary", "last_name": "Smith"}),
                        "type": "person",
                    }
                ],
                "date_from": "all",
            }
        )
        date_filter_query = filter.date_filter_Q
        self.assertEqual(date_filter_query, Q())

    def test_default_filter_by_date_from(self):
        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "name",
                        "value": json.dumps({"first_name": "Mary", "last_name": "Smith"}),
                        "type": "person",
                    }
                ],
            }
        )
        one_week_ago = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        date_filter_query = filter.date_filter_Q
        self.assertEqual(date_filter_query, Q(timestamp__gte=one_week_ago))
