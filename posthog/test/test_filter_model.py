import json

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone

from posthog.api.test.base import BaseTest
from posthog.models import Element, Event, Filter, Person, Property


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
            data={"events": [{"id": "$pageview"}], "display": "ActionsLineGraph", "compare": True}
        ).to_dict()
        self.assertEqual(list(filter.keys()), ["events", "display", "compare"])


class TestSelectors(BaseTest):
    def test_selectors(self):
        event1 = Event.objects.create(
            team=self.team,
            event="$autocapture",
            elements=[Element.objects.create(tag_name="a", order=0), Element.objects.create(tag_name="div", order=1),],
        )
        event2 = Event.objects.create(team=self.team, event="$autocapture")
        filter = Filter(data={"properties": [{"key": "selector", "value": "div > a", "type": "element"}]})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events.count(), 1)


class TestPropertiesToQ(BaseTest):
    def test_simple(self):
        Event.objects.create(team=self.team, event="$pageview")
        Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url": "https://whatever.com"}})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events.count(), 1)

    def test_contains(self):
        Event.objects.create(team=self.team, event="$pageview")
        event2 = Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__icontains": "whatever"}})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events.get(), event2)

    def test_regex(self):
        Event.objects.create(team=self.team, event="$pageview")
        event2 = Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__regex": "\.com$"}})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events.get(), event2)

    def test_is_not(self):
        event1 = Event.objects.create(team=self.team, event="$pageview")
        event2 = Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://something.com"},
        )
        Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__is_not": "https://whatever.com"}})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event1)
        self.assertEqual(events[1], event2)
        self.assertEqual(len(events), 2)

    def test_does_not_contain(self):
        event1 = Event.objects.create(team=self.team, event="$pageview")
        event2 = Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://something.com"},
        )
        Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://whatever.com"},
        )
        filter = Filter(data={"properties": {"$current_url__not_icontains": "whatever.com"}})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event1)
        self.assertEqual(events[1], event2)
        self.assertEqual(len(events), 2)

    def test_multiple(self):
        event2 = Event.objects.create(
            team=self.team,
            event="$pageview",
            properties={"$current_url": "https://something.com", "another_key": "value",},
        )
        Event.objects.create(
            team=self.team, event="$pageview", properties={"$current_url": "https://something.com"},
        )
        filter = Filter(data={"properties": {"$current_url__icontains": "something.com", "another_key": "value",}})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_user_properties(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["person1"], properties={"group": 1})
        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"], properties={"group": 2})
        event2 = Event.objects.create(
            team=self.team,
            distinct_id="person1",
            event="$pageview",
            properties={"$current_url": "https://something.com", "another_key": "value",},
        )
        Event.objects.create(
            team=self.team,
            distinct_id="person2",
            event="$pageview",
            properties={"$current_url": "https://something.com"},
        )
        filter = Filter(data={"properties": [{"key": "group", "value": 1, "type": "person"}]})
        events = Event.objects.add_person_id(self.team.pk).filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_boolean_filters(self):
        event1 = Event.objects.create(team=self.team, event="$pageview")
        event2 = Event.objects.create(team=self.team, event="$pageview", properties={"is_first_user": True})
        filter = Filter(data={"properties": [{"key": "is_first_user", "value": "true"}]})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_is_not_set_and_is_set(self):
        event1 = Event.objects.create(team=self.team, event="$pageview")
        event2 = Event.objects.create(team=self.team, event="$pageview", properties={"is_first_user": True})
        filter = Filter(
            data={"properties": [{"key": "is_first_user", "operator": "is_not_set", "value": "is_not_set",}]}
        )
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 1)

        filter = Filter(data={"properties": [{"key": "is_first_user", "operator": "is_set", "value": "is_set"}]})
        events = Event.objects.filter(filter.properties_to_Q(team_id=self.team.pk))

    def test_json_object(self):
        person1 = Person.objects.create(
            team=self.team, distinct_ids=["person1"], properties={"name": {"first_name": "Mary", "last_name": "Smith"}},
        )
        event1 = Event.objects.create(
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
        events = Event.objects.add_person_id(self.team.pk).filter(filter.properties_to_Q(team_id=self.team.pk))
        self.assertEqual(events[0], event1)
        self.assertEqual(len(events), 1)


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
