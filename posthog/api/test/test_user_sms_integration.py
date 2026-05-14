from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from rest_framework import status

from posthog.api.user_sms_integration import (
    SMS_VERIFICATION_MAX_ATTEMPTS,
    SMS_VERIFICATION_TTL_SECONDS,
    _verification_cache_key,
)
from posthog.clients.sendblue import SendBlueError, SendBlueNotConfigured
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

START_URL = "/api/users/@me/sms/start_verification/"
VERIFY_URL = "/api/users/@me/sms/verify/"
LIST_URL = "/api/users/@me/sms/"


class TestUserSMSIntegrationEndpoints(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client.force_login(self.user)
        patcher = patch("posthog.api.user_sms_integration.get_sendblue_client")
        self.mock_get_client = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_client = MagicMock()
        self.mock_get_client.return_value = self.mock_client

    def _seed_verification(self, phone: str = "+14155552671", code: str = "123456", attempts: int = 0) -> None:
        cache.set(
            _verification_cache_key(self.user),
            {"phone": phone, "code": code, "attempts": attempts},
            timeout=SMS_VERIFICATION_TTL_SECONDS,
        )

    def test_start_verification_caches_code_and_sends_sms(self):
        response = self.client.post(START_URL, {"phone_number": "+14155552671"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["phone_number"], "+14155552671")
        cached = cache.get(_verification_cache_key(self.user))
        self.assertIsNotNone(cached)
        self.assertEqual(cached["phone"], "+14155552671")
        self.assertEqual(cached["attempts"], 0)
        self.mock_client.send_message.assert_called_once()
        body = self.mock_client.send_message.call_args.kwargs["body"]
        self.assertIn(cached["code"], body)

    def test_start_verification_normalizes_phone_number(self):
        response = self.client.post(START_URL, {"phone_number": "+1 (415) 555-2671"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["phone_number"], "+14155552671")

    def test_start_verification_rejects_invalid_phone_format(self):
        response = self.client.post(START_URL, {"phone_number": "555-1234"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(cache.get(_verification_cache_key(self.user)))
        self.mock_client.send_message.assert_not_called()

    def test_start_verification_rejects_phone_linked_to_another_user(self):
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "pw")
        UserIntegration.objects.create(
            user=other_user,
            kind=UserIntegration.IntegrationKind.SMS,
            integration_id="+14155552671",
            config={},
            sensitive_config={},
        )
        response = self.client.post(START_URL, {"phone_number": "+14155552671"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_client.send_message.assert_not_called()

    def test_start_verification_returns_400_when_sendblue_not_configured(self):
        self.mock_get_client.side_effect = SendBlueNotConfigured("not configured")
        response = self.client.post(START_URL, {"phone_number": "+14155552671"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_start_verification_clears_cache_when_send_fails(self):
        self.mock_client.send_message.side_effect = SendBlueError("boom")
        response = self.client.post(START_URL, {"phone_number": "+14155552671"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(
            cache.get(_verification_cache_key(self.user)),
            "an unsent code must not linger in the cache after a SendBlue failure",
        )

    def test_verify_creates_integration_on_correct_code(self):
        self._seed_verification(phone="+14155552671", code="123456")
        response = self.client.post(VERIFY_URL, {"phone_number": "+14155552671", "code": "123456"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["phone_number"], "+14155552671")
        self.assertIsNone(cache.get(_verification_cache_key(self.user)))
        self.assertTrue(
            UserIntegration.objects.filter(
                user=self.user, kind=UserIntegration.IntegrationKind.SMS, integration_id="+14155552671"
            ).exists()
        )

    def test_verify_rejects_wrong_code_and_increments_attempts(self):
        self._seed_verification(code="123456")
        response = self.client.post(VERIFY_URL, {"phone_number": "+14155552671", "code": "999999"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        cached = cache.get(_verification_cache_key(self.user))
        self.assertIsNotNone(cached, "challenge should still be active after one wrong attempt")
        self.assertEqual(cached["attempts"], 1)

    def test_verify_invalidates_challenge_after_max_attempts(self):
        self._seed_verification(code="123456")
        for _ in range(SMS_VERIFICATION_MAX_ATTEMPTS):
            response = self.client.post(VERIFY_URL, {"phone_number": "+14155552671", "code": "999999"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(
            cache.get(_verification_cache_key(self.user)),
            "challenge must be deleted after max attempts to block brute-force",
        )
        response = self.client.post(VERIFY_URL, {"phone_number": "+14155552671", "code": "123456"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            UserIntegration.objects.filter(user=self.user, kind=UserIntegration.IntegrationKind.SMS).exists()
        )

    def test_verify_rejects_when_no_active_challenge(self):
        response = self.client.post(VERIFY_URL, {"phone_number": "+14155552671", "code": "123456"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_rejects_when_submitted_phone_differs_from_cached(self):
        self._seed_verification(phone="+14155552671", code="123456")
        response = self.client.post(VERIFY_URL, {"phone_number": "+14155552672", "code": "123456"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        cached = cache.get(_verification_cache_key(self.user))
        self.assertEqual(cached["attempts"], 0, "phone mismatch must not consume an attempt")

    def test_list_returns_verified_phones(self):
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.SMS,
            integration_id="+14155552671",
            config={},
            sensitive_config={},
        )
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["phone_number"], "+14155552671")

    def test_destroy_phone_removes_integration(self):
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.SMS,
            integration_id="+14155552671",
            config={},
            sensitive_config={},
        )
        response = self.client.delete(f"{LIST_URL}+14155552671/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            UserIntegration.objects.filter(user=self.user, kind=UserIntegration.IntegrationKind.SMS).exists()
        )
