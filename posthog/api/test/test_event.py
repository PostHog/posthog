from .base import BaseTest
from posthog.models import Event, Person, Element


class TestEvents(BaseTest):
    TESTS_API = True 
    ENDPOINT = 'event'

    def test_filter_events(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'$email': 'tim@posthog.com'}, distinct_ids=[2, 'some-random-uid'], team=self.team)

        event1 = Event.objects.create(team=self.team, properties={"distinct_id": "2"}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-random-uid'}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-other-one'}, ip='8.8.8.8')
        Element.objects.create(tag_name='button', el_text='something', nth_child=0, nth_of_type=0, event=event1, order=0, team=self.team)


        response = self.client.get('/api/event/?distinct_id=2').json()
        self.assertEqual(response['results'][0]['person'], 'tim@posthog.com')
        self.assertEqual(response['results'][0]['elements'][0]['tag_name'], 'button')

    def test_filter_by_person(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'$email': 'tim@posthog.com'}, distinct_ids=[2, 'some-random-uid'], team=self.team)

        Event.objects.create(team=self.team, properties={"distinct_id": "2"}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-random-uid'}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-other-one'}, ip='8.8.8.8')

        response = self.client.get('/api/event/?person_id=%s' % person.pk).json()
        self.assertEqual(len(response['results']), 2)

    def test_get_elements(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        event1 = Event.objects.create(team=self.team, ip='8.8.8.8')
        event2 = Event.objects.create(team=self.team, ip='8.8.8.8')
        event3 = Event.objects.create(team=self.team, ip='8.8.8.8')
        event4 = Event.objects.create(team=self.team, ip='8.8.8.8')
        Element.objects.create(tag_name='button', el_text='something', nth_child=0, nth_of_type=0, event=event1, order=0, team=self.team)
        Element.objects.create(tag_name='button', el_text='something', nth_child=0, nth_of_type=0, event=event2, order=0, team=self.team)
        Element.objects.create(tag_name='button', el_text='something else', nth_child=0, nth_of_type=0, event=event3, order=0, team=self.team)
        Element.objects.create(tag_name='input', el_text='', nth_child=0, nth_of_type=0, event=event3, order=0, team=self.team)
        
        response = self.client.get('/api/event/elements/').json()
        self.assertEqual(response[0]['name'], 'button with text "something"')
        self.assertEqual(response[0]['count'], 2)
        self.assertEqual(response[1]['name'], 'button with text "something else"')
        self.assertEqual(response[1]['count'], 1)

        self.assertEqual(response[2]['name'], 'input with text ""')
        self.assertEqual(response[2]['count'], 1)