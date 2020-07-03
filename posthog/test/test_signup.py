from django.test import TestCase, Client
from posthog.models import User, Dashboard, DashboardItem, Action, Person, Event, Team
from social_django.strategy import DjangoStrategy
from social_django.models import DjangoStorage
from social_core.utils import module_member
from posthog.urls import social_create_user


class TestSignup(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_signup_new_team(self):
        with self.settings(TEST=False):
            response = self.client.post(
                "/setup_admin",
                {
                    "company_name": "ACME Inc.",
                    "name": "Jane",
                    "email": "jane@acme.com",
                    "password": "hunter2",
                    "emailOptIn": "on",
                },
                follow=True,
            )
        self.assertRedirects(response, "/")

        user = User.objects.get()
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.email, "jane@acme.com")
        self.assertTrue(user.email_opt_in)

        team = user.team_set.get()
        self.assertEqual(team.name, "ACME Inc.")
        self.assertEqual(team.users.all()[0], user)

        action = Action.objects.get(team=team)
        self.assertEqual(action.name, "Pageviews")
        self.assertEqual(action.steps.all()[0].event, "$pageview")

        dashboards = Dashboard.objects.filter(team=team).order_by("id")
        self.assertEqual(dashboards[0].name, "Default")
        self.assertEqual(dashboards[0].team, team)

        items = DashboardItem.objects.filter(team=team).order_by("id")
        self.assertEqual(items[0].dashboard, dashboards[0])
        self.assertEqual(items[0].name, "Pageviews this week")
        self.assertEqual(items[0].type, "ActionsLineGraph")
        self.assertEqual(items[0].filters["events"][0]["id"], "$pageview")

        self.assertEqual(items[1].dashboard, dashboards[0])
        self.assertEqual(items[1].filters["events"][0]["id"], "$pageview")
        self.assertEqual(items[1].type, "ActionsTable")

    def test_signup_to_team(self):
        team = Team.objects.create_with_data(
            name="test", users=[User.objects.create_user(email="adminuser@posthog.com")]
        )
        with self.settings(TEST=False):
            response = self.client.post(
                "/signup/{}".format(team.signup_token),
                {"name": "Jane", "email": "jane@acme.com", "password": "hunter2", "emailOptIn": "",},
                follow=True,
            )
        self.assertRedirects(response, "/")
    
    def test_setup_admin_invalid(self):
        default_req_args = {
                    "company_name": "ACME Inc.",
                    "name": "Jane",
                    "email": "jane@acme.com",
                    "password": "hunter2",
                    "emailOptIn": "on",
        }
        with self.settings(TEST=False):
            # Check invalid company name with all other fields valid
            invalid_company_req = {**default_req_args}
            invalid_company_req["company_name"] = ""
            invalid_company_res = self.client.post("/setup_admin", invalid_company_req, follow=True)
            # Check invalid name with all other fields valid
            invalid_name_req = {**default_req_args}
            invalid_name_req["name"] = ""
            invalid_name_res = self.client.post("/setup_admin", invalid_name_req, follow=True)
            # Check invalid email with all other fields valid
            invalid_email_req = {**default_req_args}
            invalid_email_req["email"] = "janeacme"
            invalid_email_res = self.client.post("/setup_admin", invalid_email_req, follow=True)
            # Check invalid password with all other fields valid
            invalid_password_req = {**default_req_args}
            invalid_password_req["password"] = ""
            invalid_password_res = self.client.post("/setup_admin", invalid_password_req, follow=True)

        ERROR_MSG = "Please make sure no fields are empty and that the email entered is valid."
        self.assertContains(invalid_company_res, ERROR_MSG)
        self.assertContains(invalid_name_res, ERROR_MSG)
        self.assertContains(invalid_email_res, ERROR_MSG)
        self.assertContains(invalid_password_res, ERROR_MSG)
    
    def test_signup_to_team_invalid(self):
        default_req_args = {
                    "name": "Jane",
                    "email": "jane@acme.com",
                    "password": "hunter2",
                    "emailOptIn": "on",
        }
        team = Team.objects.create_with_data(
            name="test", 
            users=[User.objects.create_user(email="adminuser@posthog.com")]
        )
        with self.settings(TEST=False):
            invalid_name_req = {**default_req_args}
            invalid_name_req["name"] = ""
            invalid_name_res = self.client.post(
                "/signup/{}".format(team.signup_token),
                invalid_name_req,
                follow=True,
            )
            invalid_email_req = {**default_req_args}
            invalid_email_req["email"] = "janeacme"
            invalid_email_res = self.client.post(
                "/signup/{}".format(team.signup_token),
                invalid_email_req,
                follow=True,
            )
            invalid_password_req = {**default_req_args}
            invalid_password_req["password"] = ""
            invalid_password_res = self.client.post(
                "/signup/{}".format(team.signup_token),
                invalid_password_req,
                follow=True,
            )
        ERROR_MSG = "Please make sure no fields are empty and that the email entered is valid."
        self.assertContains(invalid_name_res, ERROR_MSG)
        self.assertContains(invalid_email_res, ERROR_MSG)
        self.assertContains(invalid_password_res, ERROR_MSG)

class TestSocialSignup(TestCase):
    def setUp(self):
        super().setUp()
        Backend = module_member("social_core.backends.github.GithubOAuth2")
        self.strategy = DjangoStrategy(DjangoStorage)
        self.backend = Backend(self.strategy, redirect_uri="/complete/github")
        self.login_redirect_url = "/"

    def test_custom_create_user_pipeline(self):
        Team.objects.create(signup_token="faketoken")
        details = {
            "username": "fake_username",
            "email": "fake@email.com",
            "fullname": "bob bob",
            "first_name": "bob",
            "last_name": "bob",
        }

        # try to create user without a signup token
        result = social_create_user(self.strategy, details, self.backend)
        count = User.objects.count()
        self.assertEqual(count, 0)

        # try to create user without a wrong/unassociated token
        self.strategy.session_set("signup_token", "wrongtoken")
        result = social_create_user(self.strategy, details, self.backend)
        count = User.objects.count()
        self.assertEqual(count, 0)

        # create user
        self.strategy.session_set("signup_token", "faketoken")
        result = social_create_user(self.strategy, details, self.backend)
        user = User.objects.get()
        self.assertEqual(result["is_new"], True)
        self.assertEqual(user.email, "fake@email.com")
