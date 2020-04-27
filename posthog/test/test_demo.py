from django.test import TestCase, Client
from posthog.models import User, DashboardItem, Action, Person, Event, Funnel
from posthog.api.test.base import BaseTest

class TestDemo(BaseTest):
    TESTS_API = True

    def test_create_demo_data(self):
        self.client.get('/demo')
        self.assertEqual(Event.objects.count(), 190)
        self.assertEqual(Person.objects.count(), 100)
        self.assertEqual(Funnel.objects.count(), 1)
        self.assertEqual(Action.objects.count(), 3)

        self.assertEqual(Action.objects.all()[1].events.count(), 9)

    def test_do_not_create_demo_data_if_already_exists(self):
        Event.objects.create(team=self.team, event='random event')
        self.client.get('/demo')
        self.assertEqual(Event.objects.count(), 1)

    def test_delete_demo_data(self):
        self.client.get('/demo')
        self.assertEqual(Event.objects.count(), 190)
        Person.objects.create(team=self.team, distinct_ids=['random_real_person'])
        response = self.client.delete('/delete_demo_data/').json()
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(Person.objects.count(), 1)
        self.assertEqual(Funnel.objects.count(), 0)
        self.assertEqual(Action.objects.count(), 0)
