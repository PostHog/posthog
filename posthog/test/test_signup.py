from django.test import TestCase, Client
from posthog.models import User, DashboardItem, Action

class TestSignup(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
     
    def test_signup_new_team(self):
        with self.settings(TEST=False):
            response = self.client.post('/setup_admin', {'company_name': 'ACME Inc.', 'name': 'Jane', 'email': 'jane@acme.com', 'password': 'hunter2'}, follow=True)
        self.assertRedirects(response, '/')

        user = User.objects.get() 
        self.assertEqual(user.first_name, 'Jane')
        self.assertEqual(user.email, 'jane@acme.com')

        team = user.team_set.get()
        self.assertEqual(team.name, 'ACME Inc.')
        self.assertEqual(team.users.all()[0], user)

        action = Action.objects.get(team=team)
        self.assertEqual(action.name, 'Pageviews')
        self.assertEqual(action.steps.all()[0].event, '$pageview')

        items = DashboardItem.objects.filter(team=team).order_by('id')
        self.assertEqual(items[0].name, 'Pageviews this week')
        self.assertEqual(items[0].type, 'ActionsLineGraph')
        self.assertEqual(items[0].filters['actions'], [action.pk])

        self.assertEqual(items[1].filters['actions'], [action.pk])
        self.assertEqual(items[1].type, 'ActionsTable')

        self.assertEqual(items[2].name, 'All actions')