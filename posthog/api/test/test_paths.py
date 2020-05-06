from .base import BaseTest
from posthog.models import Person, Event
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

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


        date_from = now() - relativedelta(days=7)
        response = self.client.get('/api/paths/?date_from=' + date_from.strftime("%Y-%m-%d")).json()
        self.assertEqual(len(response), 4)

        date_to = now() + relativedelta(days=7)
        response = self.client.get('/api/paths/?date_to=' + date_to.strftime("%Y-%m-%d")).json()
        self.assertEqual(len(response), 4)

        date_from = now() + relativedelta(days=7)
        response = self.client.get('/api/paths/?date_from=' + date_from.strftime("%Y-%m-%d")).json()
        self.assertEqual(len(response), 0)

        date_to = now() - relativedelta(days=7)
        response = self.client.get('/api/paths/?date_to=' + date_to.strftime("%Y-%m-%d")).json()
        self.assertEqual(len(response), 0)

        date_from = now() - relativedelta(days=7)
        date_to = now() + relativedelta(days=7)
        response = self.client.get('/api/paths/?date_from=' + date_from.strftime("%Y-%m-%d") + '&date_to=' + date_to.strftime("%Y-%m-%d")).json()
        self.assertEqual(len(response), 4)

        date_from = now() + relativedelta(days=7)
        date_to = now() - relativedelta(days=7)
        response = self.client.get('/api/paths/?date_from=' + date_from.strftime("%Y-%m-%d") + '&date_to=' + date_to.strftime("%Y-%m-%d")).json()
        self.assertEqual(len(response), 0)

    def test_paths_in_window(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=['person_1'])

        first_day = now() - relativedelta(days=5)
        second_day = now() - relativedelta(days=4)
        begin_query_range = now() - relativedelta(days=7)

        with freeze_time(first_day.strftime("%Y-%m-%d")):
            Event.objects.create(properties={'$current_url': '/'}, distinct_id='person_1', event='$pageview', team=self.team)
            Event.objects.create(properties={'$current_url': '/about'}, distinct_id='person_1', event='$pageview', team=self.team)
        
        with freeze_time(second_day.strftime("%Y-%m-%d")):
            Event.objects.create(properties={'$current_url': '/'}, distinct_id='person_1', event='$pageview', team=self.team)
            Event.objects.create(properties={'$current_url': '/about'}, distinct_id='person_1', event='$pageview', team=self.team)

        response = self.client.get('/api/paths/?date_from=' + begin_query_range.strftime("%Y-%m-%d")).json()

        self.assertEqual(response[0]['source'], '1_/')
        self.assertEqual(response[0]['target'], '2_/about')
        self.assertEqual(response[0]['value'], 2)

