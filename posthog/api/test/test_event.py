from .base import BaseTest
from posthog.models import Event, Person


class TestEvents(BaseTest):
    TESTS_API = True 
    ENDPOINT = 'event'

    def test_users(self):
        user = self._create_user('tim')
        self.client.force_login(user)
        person = Person.objects.create(distinct_ids=[2, 'some-random-uid', 'some-other-one'], team=self.team)

        Event.objects.create(team=self.team, properties={"distinct_id": 2}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-random-uid'}, ip='8.8.8.8')
        Event.objects.create(team=self.team, properties={"distinct_id": 'some-other-one'}, ip='8.8.8.8')


        response = self.client.get('/api/event/person/').json()
        self.assertEqual(response[0]['id'], person.pk)