import uuid

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.instance_setting import override_instance_config
from posthog.urls import region_host_from_current_instance


class TestUrls(APIBaseTest):
    def test_logged_out_user_is_redirected_to_login(self):
        self.client.logout()

        # Root path should redirect to /login without ?next=/ since "/" is the default destination
        response = self.client.get("/")
        self.assertRedirects(response, "/login")

        response = self.client.get("/events")
        self.assertRedirects(response, "/login?next=/events")

        # Complex URL
        response = self.client.get(
            '/insights/new?interval=day&display=ActionsLineGraph&events=[{"id":"$pageview","name":"$pageview","type":"events","order":0}]&properties=[]'
        )

        # Test that the URL is properly encoded to redirect the user to the final destination
        self.assertRedirects(
            response,
            "/login?next=/insights/new%3Finterval%3Dday%26display%3DActionsLineGraph%26events%3D%5B%257B%2522id%2522%3A%2522%24pageview%2522%2C%2522name%2522%3A%2522%24pageview%2522%2C%2522type%2522%3A%2522events%2522%2C%2522order%2522%3A0%257D%5D%26properties%3D%5B%5D",
            fetch_redirect_response=False,
        )

    @parameterized.expand(
        [
            ("eu", "https://eu.posthog.com", "https://eu.posthog.com/organization/billing"),
            ("us", "https://us.posthog.com", "https://us.posthog.com/organization/billing"),
        ]
    )
    def test_app_host_deep_link_redirects_to_logged_in_region(self, _name, cookie_value, expected_location):
        # /organization/billing is behind login_required; the region redirect must fire first,
        # so a logged-out EU user reaches EU instead of the US login page.
        self.client.logout()
        self.client.cookies["ph_current_instance"] = cookie_value
        response = self.client.get("/organization/billing", HTTP_HOST="app.posthog.com", follow=False)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], expected_location)

    def test_app_host_deep_link_without_region_cookie_falls_through_to_login(self):
        self.client.logout()
        self.client.cookies.pop("ph_current_instance", None)
        response = self.client.get("/organization/billing", HTTP_HOST="app.posthog.com", follow=False)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("/login", response["Location"])

    def test_app_host_deep_link_without_region_cookie_falls_back_to_us_when_redirect_app_to_us(self):
        # With no region cookie, REDIRECT_APP_TO_US routes app.posthog.com to US before the auth gate.
        self.client.logout()
        self.client.cookies.pop("ph_current_instance", None)
        with override_instance_config("REDIRECT_APP_TO_US", True):
            response = self.client.get("/organization/billing", HTTP_HOST="app.posthog.com", follow=False)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "https://us.posthog.com/organization/billing")

    def test_integration_connect_redirect_authenticated(self):
        response = self.client.get(
            f"/integrations/connect/github/?project_id={self.team.id}&connect_from=slack", follow=False
        )
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        location = response["Location"]
        self.assertIn(f"/api/environments/{self.team.id}/integrations/authorize/", location)
        self.assertIn("kind=github", location)
        self.assertIn("account-connected", location)
        self.assertIn("connect_from%3Dslack", location)

    def test_integration_connect_redirect_requires_login(self):
        self.client.logout()
        response = self.client.get("/integrations/connect/github/?project_id=1&connect_from=slack", follow=False)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("/login", response["Location"])

    def test_integration_connect_redirect_rejects_bad_kind(self):
        response = self.client.get(f"/integrations/connect/notreal/?project_id={self.team.id}&connect_from=slack")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_integration_connect_redirect_rejects_bad_connect_from(self):
        response = self.client.get(f"/integrations/connect/github/?project_id={self.team.id}&connect_from=evil")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_routes_get_loaded_on_the_frontend(self):
        self.client.logout()

        response = self.client.get("/signup")
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # no redirect

        response = self.client.get(f"/signup/{uuid.uuid4()}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/preflight")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/login")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("no_slash_no_qs", "/sign-up", "/signup"),
            ("trailing_slash_no_qs", "/sign-up/", "/signup"),
            ("no_slash_with_qs", "/sign-up?email=foo%40bar.com", "/signup?email=foo%40bar.com"),
            ("trailing_slash_with_qs", "/sign-up/?email=foo%40bar.com", "/signup?email=foo%40bar.com"),
        ]
    )
    def test_sign_up_redirects_to_signup(self, _name, request_path, expected_location):
        self.client.logout()
        response = self.client.get(request_path, follow=False)
        self.assertEqual(response.status_code, status.HTTP_301_MOVED_PERMANENTLY)
        self.assertEqual(response["Location"], expected_location)

    @parameterized.expand(
        [
            ("no_query_string", "/admin", "/admin/"),
            ("with_query_string", "/admin?foo=bar&baz=qux", "/admin/?foo=bar&baz=qux"),
        ]
    )
    @override_settings(ADMIN_PORTAL_ENABLED=True)
    def test_admin_without_trailing_slash_redirects(self, _name, request_path, expected_location):
        # APPEND_SLASH is disabled globally, so /admin needs an explicit redirect
        response = self.client.get(request_path, follow=False)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], expected_location)

    def test_authorize_and_redirect_domain(self):
        self.team.app_urls = ["https://domain.com", "https://not.com"]
        self.team.save()

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://not-permitted.com",
            headers={"referer": "https://not-permitted.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        content = response.content.decode()
        self.assertIn("Domain not authorized", content)
        self.assertIn("not-permitted.com", content)
        self.assertIn("/settings/project-toolbar#authorized-urls", content)

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com", headers={"referer": "https://not.com"}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same domain as the referer: not.com" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=http://domain.com", headers={"referer": "https://domain.com"}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same scheme as the referer: https" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com:555", headers={"referer": "https://domain.com:443"}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same port as the referer: 443" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com:555",
            headers={"referer": "https://domain.com/no-port"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same port as the referer: no port in URL" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com/sdf", headers={"referer": "https://domain.com/asd"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # TODO: build frontend before backend tests, or find a way to mock the template
        # self.assertContains(
        #     response,
        #     "Do you want to give the PostHog Toolbar on <strong>https://domain.com/sdf</strong> access to your PostHog data?",
        # )


class TestRegionHostFromCurrentInstance(SimpleTestCase):
    @parameterized.expand(
        [
            ("eu", "https://eu.posthog.com", "eu.posthog.com"),
            ("us", "https://us.posthog.com", "us.posthog.com"),
            ("with_port", "https://eu.posthog.com:8123", "eu.posthog.com"),
            ("wrapping_quotes", '"https://eu.posthog.com"', "eu.posthog.com"),
            ("app_is_not_a_region", "https://app.posthog.com", None),
            ("unknown_host_is_rejected", "https://evil.example.com", None),
            ("none", None, None),
            ("empty", "", None),
            ("not_a_url", "yo ho ho", None),
        ]
    )
    def test_region_host_from_current_instance(self, _name, cookie_value, expected):
        self.assertEqual(region_host_from_current_instance(cookie_value), expected)
