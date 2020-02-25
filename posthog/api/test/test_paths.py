from .base import BaseTest
from posthog.models import Person, Event

class TestPaths(BaseTest):
    TESTS_API = True

    def test_paths(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=['person_1'])
        Event.objects.create(properties={'$current_url': '/'}, distinct_id='person_1', event='$pageview', team=self.team)
        Event.objects.create(properties={'$current_url': '/about'}, distinct_id='person_1', event='$pageview', team=self.team)

        person2 = Person.objects.create(team=self.team, distinct_ids=['person_2'])
        Event.objects.create(properties={'$current_url': '/'}, distinct_id='person_2', event='$pageview', team=self.team)
        Event.objects.create(properties={'$current_url': '/pricing'}, distinct_id='person_2', event='$pageview', team=self.team)
        Event.objects.create(properties={'$current_url': '/about'}, distinct_id='person_2', event='$pageview', team=self.team)

        person3 = Person.objects.create(team=self.team, distinct_ids=['person_3'])
        Event.objects.create(properties={'$current_url': '/pricing'}, distinct_id='person_3', event='$pageview', team=self.team)
        Event.objects.create(properties={'$current_url': '/'}, distinct_id='person_3', event='$pageview', team=self.team)

        person3 = Person.objects.create(team=self.team, distinct_ids=['person_4'])
        Event.objects.create(properties={'$current_url': '/'}, distinct_id='person_4', event='$pageview', team=self.team)
        Event.objects.create(properties={'$current_url': '/pricing'}, distinct_id='person_4', event='$pageview', team=self.team)


        response = self.client.get('/api/paths/').json()
        self.assertEqual(response[0]['source'], '1_/', response)
        self.assertEqual(response[0]['target'], '2_/pricing')
        self.assertEqual(response[0]['value'], 2)

        self.assertEqual(response[1]['source'], '1_/')
        self.assertEqual(response[1]['target'], '2_/about')
        self.assertEqual(response[1]['value'], 1)

        self.assertEqual(response[2]['source'], '1_/pricing')
        self.assertEqual(response[2]['target'], '2_/')
        self.assertEqual(response[2]['value'], 1)

        self.assertEqual(response[3]['source'], '2_/pricing', response[3])
        self.assertEqual(response[3]['target'], '3_/about')
        self.assertEqual(response[3]['value'], 1)