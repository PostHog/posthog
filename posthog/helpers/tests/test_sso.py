from django.test import RequestFactory, SimpleTestCase

from posthog.helpers.sso import sso_failure_redirect_url


class TestSsoFailureRedirectUrl(SimpleTestCase):
    def test_error_detail_stays_ahead_of_the_fragment_on_reauth(self):
        request = RequestFactory().get("/complete/google-oauth2/", {"next": "/settings/user?tab=security#section"})

        url = sso_failure_redirect_url(request, "social_login_failure", is_reauth=True, error_detail="Nope.")

        self.assertEqual(url, "/settings/user?tab=security&error_code=social_login_failure&error_detail=Nope.#section")
