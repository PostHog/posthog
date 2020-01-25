from .base import BaseTest
from posthog.models import Event, Person


class TestEvents(BaseTest):
    TESTS_API = True 
    ENDPOINT = 'event'

    def test_filter_events(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'$email': 'tim@posthog.com'}, distinct_ids=[2, 'some-random-uid'], team=self.team)

        Event.objects.create(team=self.team, properties={"distinct_id": "2"}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-random-uid'}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-other-one'}, ip='8.8.8.8')


        response = self.client.get('/api/event/?distinct_id=2').json()
        self.assertEqual(response['results'][0]['person'], 'tim@posthog.com')

    def test_filter_by_person(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(properties={'$email': 'tim@posthog.com'}, distinct_ids=[2, 'some-random-uid'], team=self.team)

        Event.objects.create(team=self.team, properties={"distinct_id": "2"}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-random-uid'}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-other-one'}, ip='8.8.8.8')


        response = self.client.get('/api/event/?person_id=%s' % person.pk).json()
        self.assertEqual(len(response['results']), 2)

