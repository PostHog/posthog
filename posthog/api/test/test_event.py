from .base import BaseTest
from posthog.models import Event, Person, Element


class TestEvents(BaseTest):
    TESTS_API = True 
    ENDPOINT = 'event'

    def test_filter_events(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'$email': 'tim@posthog.com'}, team=self.team, distinct_ids=["2", 'some-random-uid'])

        event1 = Event.objects.create(team=self.team, distinct_id="2", ip='8.8.8.8')
        Event.objects.create(team=self.team, distinct_id='some-random-uid', ip='8.8.8.8')
        Event.objects.create(team=self.team, distinct_id='some-other-one', ip='8.8.8.8')
        Element.objects.create(tag_name='button', text='something', event=event1)


        response = self.client.get('/api/event/?distinct_id=2').json()
        self.assertEqual(response['results'][0]['person'], 'tim@posthog.com')
        self.assertEqual(response['results'][0]['elements'][0]['tag_name'], 'button')

    def test_filter_by_person(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'$email': 'tim@posthog.com'}, distinct_ids=["2", 'some-random-uid'], team=self.team)

        Event.objects.create(team=self.team, distinct_id="2", ip='8.8.8.8')
        Event.objects.create(team=self.team, distinct_id='some-random-uid', ip='8.8.8.8')
        Event.objects.create(team=self.team, distinct_id='some-other-one', ip='8.8.8.8')

        response = self.client.get('/api/event/?person_id=%s' % person.pk).json()
        self.assertEqual(len(response['results']), 2)

    def test_get_elements(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        event1 = Event.objects.create(team=self.team, ip='8.8.8.8')
        event2 = Event.objects.create(team=self.team, ip='8.8.8.8')
        event3 = Event.objects.create(team=self.team, ip='8.8.8.8')
        event4 = Event.objects.create(team=self.team, ip='8.8.8.8')
        Element.objects.create(tag_name='button', text='something', event=event1)
        Element.objects.create(tag_name='button', text='something', event=event2)
        Element.objects.create(tag_name='button', text='something else', event=event3)
        Element.objects.create(tag_name='input', text='', event=event3)
        
        response = self.client.get('/api/event/elements/').json()
        self.assertEqual(response[0]['name'], 'button with text "something"')
        self.assertEqual(response[0]['count'], 2)
        self.assertEqual(response[1]['name'], 'button with text "something else"')
        self.assertEqual(response[1]['count'], 1)

        self.assertEqual(response[2]['name'], 'input with text ""')
        self.assertEqual(response[2]['count'], 1)