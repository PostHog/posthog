from .base import BaseTest
from posthog.models import Person, Event

class TestPerson(BaseTest):
    TESTS_API = True

    def test_queries(self):
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id', 'distinct_id'])
        Event.objects.create(team=self.team, distinct_id='distinct_id')
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id_2', 'distinct_id_2'])
        Event.objects.create(team=self.team, distinct_id='distinct_id_2')
        Person.objects.create(team=self.team, distinct_ids=['anonymous_id_3', 'distinct_id_3'])
        Event.objects.create(team=self.team, distinct_id='distinct_id_3')

        with self.assertNumQueries(8):
            response = self.client.get('/api/person/?include_last_event=1').json()

    def test_search(self):
        Person.objects.create(team=self.team, distinct_ids=['distinct_id'], properties={'email': 'someone@gmail.com'})
        Person.objects.create(team=self.team, distinct_ids=['distinct_id_2'], properties={'email': 'another@gmail.com'})
        Person.objects.create(team=self.team, distinct_ids=['distinct_id_3'], properties={})

        response = self.client.get('/api/person/?search=has:email').json()
        self.assertEqual(len(response['results']), 2)

        response = self.client.get('/api/person/?search=another@gm').json()
        self.assertEqual(len(response['results']), 1)