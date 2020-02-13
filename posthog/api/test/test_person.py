from .base import BaseTest
from posthog.models import Person, Event

class TestPerson(BaseTest):
    TESTS_API = True

    def test_queries(self):
        Person.objects.create(team=self.team, distinct_ids=['distinct_id', 'anonymous_id'])
        Event.objects.create(team=self.team, distinct_id='distinct_id')
        Person.objects.create(team=self.team, distinct_ids=['distinct_id_2', 'anonymous_id_2'])
        Event.objects.create(team=self.team, distinct_id='distinct_id_2')
        Person.objects.create(team=self.team, distinct_ids=['distinct_id_3', 'anonymous_id_3'])
        Event.objects.create(team=self.team, distinct_id='distinct_id_3')

        with self.assertNumQueries(6):
            response = self.client.get('/api/person/').json()