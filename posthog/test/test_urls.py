import uuid

import pytest
from django.conf import settings
from rest_framework import status

import posthog.urls
from posthog.test.base import APIBaseTest


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
            '/insights/new?interval=day&display=ActionsLineGraph&events=[{"id":"$pageview","name":"$pageview","type":"events","order":0}]&properties=[]',
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
