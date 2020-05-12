from posthog.api.test.base import BaseTest
from posthog.models import Filter, Property, Event, Person

class TestFilter(BaseTest):
    def test_old_style_properties(self):
        filter = Filter(data={
            'properties': {
                '$browser__is_not': 'IE7',
                '$OS': 'Mac',
            }
        })
        self.assertEqual(filter.properties[0].key, '$browser')
        self.assertEqual(filter.properties[0].operator, 'is_not')
        self.assertEqual(filter.properties[0].value, 'IE7')
        self.assertEqual(filter.properties[0].type, 'event')
        self.assertEqual(filter.properties[1].key, '$OS')
        self.assertEqual(filter.properties[1].operator, None)
        self.assertEqual(filter.properties[1].value, 'Mac')

class TestPropertiesToQ(BaseTest):
    def test_simple(self):
        Event.objects.create(team=self.team, event='$pageview')
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        filter = Filter(data={
            'properties': {'$current_url': 'https://whatever.com'}
        })
        events = Event.objects.filter(filter.properties_to_Q())
        self.assertEqual(events.count(), 1)

    def test_contains(self):
        Event.objects.create(team=self.team, event='$pageview')
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        filter = Filter(data={
            'properties': {'$current_url__icontains': 'whatever'}
        })
        events = Event.objects.filter(filter.properties_to_Q())
        self.assertEqual(events.get(), event2)

    def test_is_not(self):
        event1 = Event.objects.create(team=self.team, event='$pageview')
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://something.com'})
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        filter = Filter(data={
            'properties': {'$current_url__is_not': 'https://whatever.com'}
        })
        events = Event.objects.filter(filter.properties_to_Q())
        self.assertEqual(events[0], event1)
        self.assertEqual(events[1], event2)
        self.assertEqual(len(events), 2)

    def test_does_not_contain(self):
        event1 = Event.objects.create(team=self.team, event='$pageview')
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://something.com'})
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://whatever.com'})
        filter = Filter(data={
            'properties': {'$current_url__not_icontains': 'whatever.com'}
        })
        events = Event.objects.filter(filter.properties_to_Q())
        self.assertEqual(events[0], event1)
        self.assertEqual(events[1], event2)
        self.assertEqual(len(events), 2)

    def test_multiple(self):
        event2 = Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://something.com', 'another_key': 'value'})
        Event.objects.create(team=self.team, event='$pageview', properties={'$current_url': 'https://something.com'})
        filter = Filter(data={
            'properties': {'$current_url__icontains': 'something.com', 'another_key': 'value'}
        })
        events = Event.objects.filter(filter.properties_to_Q())
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)

    def test_user_properties(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=['person1'], properties={'group': 1})
        person2 = Person.objects.create(team=self.team, distinct_ids=['person2'], properties={'group': 2})
        event2 = Event.objects.create(team=self.team, distinct_id='person1', event='$pageview', properties={'$current_url': 'https://something.com', 'another_key': 'value'})
        Event.objects.create(team=self.team, distinct_id='person2', event='$pageview', properties={'$current_url': 'https://something.com'})
        filter = Filter(data={
            'properties': [
                {'key': 'group', 'value': 1, 'type': 'person'}
            ] 
        })
        events = Event.objects.add_person_id(self.team.pk).filter(filter.properties_to_Q())
        self.assertEqual(events[0], event2)
        self.assertEqual(len(events), 1)