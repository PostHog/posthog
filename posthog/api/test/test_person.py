from .base import BaseTest
from posthog.models import Person, Event, Cohort

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

    def test_person_property_names(self):
        Person.objects.create(team=self.team, properties={'$browser': 'whatever', '$os': 'Mac OS X'})
        Person.objects.create(team=self.team, properties={'random_prop': 'asdf'})
        Person.objects.create(team=self.team, properties={'random_prop': 'asdf'})

        response = self.client.get('/api/person/properties/').json()
        self.assertEqual(response[0]['name'], 'random_prop')
        self.assertEqual(response[0]['count'], 2)
        self.assertEqual(response[2]['name'], '$os')
        self.assertEqual(response[2]['count'], 1)
        self.assertEqual(response[1]['name'], '$browser')
        self.assertEqual(response[1]['count'], 1)

    def test_person_property_values(self):
        Person.objects.create(team=self.team, properties={'random_prop': 'asdf', 'some other prop': 'with some text'})
        Person.objects.create(team=self.team, properties={'random_prop': 'asdf'})
        Person.objects.create(team=self.team, properties={'random_prop': 'qwerty'})
        Person.objects.create(team=self.team, properties={'something_else': 'qwerty'})
        response = self.client.get('/api/person/values/?key=random_prop').json()
        self.assertEqual(response[0]['name'], 'asdf')
        self.assertEqual(response[0]['count'], 2)
        self.assertEqual(response[1]['name'], 'qwerty')
        self.assertEqual(response[1]['count'], 1)

        response = self.client.get('/api/person/values/?key=random_prop&value=qw').json()
        self.assertEqual(response[0]['name'], 'qwerty')
        self.assertEqual(response[0]['count'], 1)

    def test_filter_by_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=['person_1', 'anonymous_id'], properties={'$os': 'Chrome'})
        Person.objects.create(team=self.team, distinct_ids=['person_2'])

        cohort = Cohort.objects.create(team=self.team, groups=[{'properties': {'$os': 'Chrome'}}])
        response = self.client.get('/api/person/?cohort=%s' % cohort.pk).json()
        self.assertEqual(len(response['results']), 1, response)