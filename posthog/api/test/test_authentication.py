from unittest.mock import patch

from rest_framework import status

from posthog.test.base import APITransactionBaseTest


class TestAuthenticationAPI(APITransactionBaseTest):

    INVALID_CREDENTIALS_RESPONSE = {
        "type": "validation_error",
        "code": "invalid_credentials",
        "detail": "Invalid email or password.",
        "attr": None,
    }
    CONFIG_AUTO_LOGIN = False

    @patch("posthoganalytics.capture")
    def test_user_logs_in_with_email_and_password(self, mock_capture):
        response = self.client.post("/api/login", {"email": self.CONFIG_USER_EMAIL, "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})

        # Test that we're actually logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], self.user.email)

        # Assert the event was captured.
        mock_capture.assert_called_once_with(
            self.user.distinct_id, "user logged in", properties={"social_provider": ""}
        )

    @patch("posthoganalytics.capture")
    def test_user_cant_login_with_incorrect_password(self, mock_capture):

        invalid_passwords = ["1234", "abcdefgh", self.CONFIG_PASSWORD[:-1], "😈😈😈"]

        for password in invalid_passwords:
            response = self.client.post("/api/login", {"email": self.CONFIG_USER_EMAIL, "password": password})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json(), self.INVALID_CREDENTIALS_RESPONSE)

            # Assert user is not logged in
            response = self.client.get("/api/user/")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertNotIn("email", response.json())

        # Events never get reported
        mock_capture.assert_not_called()

    @patch("posthoganalytics.capture")
    def test_user_cant_login_with_incorrect_email(self, mock_capture):

        response = self.client.post("/api/login", {"email": "user2@posthog.com", "password": self.CONFIG_PASSWORD})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), self.INVALID_CREDENTIALS_RESPONSE)

        # Assert user is not logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn("email", response.json())

        # Events never get reported
        mock_capture.assert_not_called()

    def test_cant_login_without_required_attributes(self):
        pass

    def test_login_endpoint_is_protected_against_brute_force_attempts(self):
        pass
