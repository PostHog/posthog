import uuid

from posthog.test.base import APIBaseTest

from django.contrib.sessions.backends.base import SessionBase
from django.test import RequestFactory, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.urls import handler500


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

    def test_handler500_renders_the_service_error_page(self):
        request = RequestFactory().get("/")
        response = handler500(request)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn(b"service-error", response.content)

    def test_handler500_does_not_touch_session(self):
        # During a DB/PgBouncer outage the session store is dead and any access to it raises
        # `'SessionStore' object has no attribute '_session_cache'`. The 500 handler must render
        # without running session-touching context processors, so this must still return a clean
        # 500 with the real error page rather than re-raising inside the handler.
        request = RequestFactory().get("/")

        class _DeadSession(SessionBase):
            def __contains__(self, key):
                raise AttributeError("'SessionStore' object has no attribute '_session_cache'")

            def get(self, key, default=None):
                raise AttributeError("'SessionStore' object has no attribute '_session_cache'")

        request.session = _DeadSession()

        response = handler500(request)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn(b"service-error", response.content)

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
