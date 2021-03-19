from rest_framework import status

from posthog.test.base import APITransactionBaseTest


class TestAuthenticationAPI(APITransactionBaseTest):
    def test_user_logs_in_with_email_and_password(self):
        response = self.client.post({"email": self.CONFIG_USER_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.json(), None)

        # Test that we're actually logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

    def test_user_cant_login_with_incorrect_email_or_password(self):
        pass

    def test_cant_login_without_required_attributes(self):
        pass

    def test_login_endpoint_is_protected_against_brute_force_attempts(self):
        pass
