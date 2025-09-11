import uuid

from posthog.test.base import APIBaseTest

from rest_framework import status


class TestUrls(APIBaseTest):
    def test_logout_temporary_token_reset(self):
        # update temporary token
        self.user.temporary_token = "token123"
        self.user.save()

        # logout
        with self.settings(TEST=False):
            response = self.client.post("/logout", follow=True)
            self.assertRedirects(response, "/login")

        # no more token
        self.user.refresh_from_db()
        self.assertEqual(self.user.temporary_token, None)

    def test_logged_out_user_is_redirected_to_login(self):
        self.client.logout()

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

    def test_authorize_and_redirect_domain(self):
        self.team.app_urls = ["https://domain.com", "https://not.com"]
        self.team.save()

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://not-permitted.com",
            HTTP_REFERER="https://not-permitted.com",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to a permitted domain." in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com",
            HTTP_REFERER="https://not.com",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same domain as the referer: not.com" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=http://domain.com",
            HTTP_REFERER="https://domain.com",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same scheme as the referer: https" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com:555",
            HTTP_REFERER="https://domain.com:443",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same port as the referer: 443" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com:555",
            HTTP_REFERER="https://domain.com/no-port",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue("Can only redirect to the same port as the referer: no port in URL" in str(response.content))

        response = self.client.get(
            "/authorize_and_redirect/?redirect=https://domain.com/sdf",
            HTTP_REFERER="https://domain.com/asd",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # TODO: build frontend before backend tests, or find a way to mock the template
        # self.assertContains(
        #     response,
        #     "Do you want to give the PostHog Toolbar on <strong>https://domain.com/sdf</strong> access to your PostHog data?",
        # )
