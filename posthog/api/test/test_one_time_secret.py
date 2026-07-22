from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.one_time_secret import create_one_time_secret


class TestOneTimeSecret(APIBaseTest):
    def _make_secret(self, *, value: str = "phx_supersecret_value", created_by_id: int | None = None) -> str:
        return create_one_time_secret(
            value=value,
            secret_type="personal_api_token",
            created_by_id=created_by_id if created_by_id is not None else self.user.id,
        )

    def test_peek_returns_type_without_value(self) -> None:
        token = self._make_secret()
        response = self.client.get(f"/api/one_time_secrets/{token}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"secret_type": "personal_api_token"})

    def test_reveal_returns_value_once_then_burns(self) -> None:
        token = self._make_secret(value="phx_reveal_me_once")
        first = self.client.post(f"/api/one_time_secrets/{token}/reveal/")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.json(), {"secret_type": "personal_api_token", "value": "phx_reveal_me_once"})

        second = self.client.post(f"/api/one_time_secrets/{token}/reveal/")
        self.assertEqual(second.status_code, status.HTTP_404_NOT_FOUND)

    def test_peek_still_works_after_creation_but_not_after_reveal(self) -> None:
        token = self._make_secret()
        self.assertEqual(self.client.get(f"/api/one_time_secrets/{token}/").status_code, status.HTTP_200_OK)
        self.client.post(f"/api/one_time_secrets/{token}/reveal/")
        self.assertEqual(self.client.get(f"/api/one_time_secrets/{token}/").status_code, status.HTTP_404_NOT_FOUND)

    def test_another_user_cannot_peek_or_reveal_and_does_not_burn(self) -> None:
        # Secret owned by a different user
        other_user = self._create_user("someone-else@posthog.com")
        token = self._make_secret(created_by_id=other_user.id)

        self.assertEqual(self.client.get(f"/api/one_time_secrets/{token}/").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            self.client.post(f"/api/one_time_secrets/{token}/reveal/").status_code, status.HTTP_404_NOT_FOUND
        )

        # The rightful owner can still reveal it — the mismatched attempt did not burn it
        self.client.force_login(other_user)
        owner_reveal = self.client.post(f"/api/one_time_secrets/{token}/reveal/")
        self.assertEqual(owner_reveal.status_code, status.HTTP_200_OK)

    def test_unknown_token_is_not_found(self) -> None:
        self.assertEqual(
            self.client.get("/api/one_time_secrets/does-not-exist/").status_code, status.HTTP_404_NOT_FOUND
        )

    def test_unauthenticated_is_rejected(self) -> None:
        token = self._make_secret()
        self.client.logout()
        self.assertIn(
            self.client.get(f"/api/one_time_secrets/{token}/").status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_personal_api_key_cannot_reveal(self) -> None:
        # Session auth only: a personal API key must not be able to open the reveal endpoint,
        # so an agent holding one cannot read the secret.
        token = self._make_secret()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(user=self.user, label="test", secure_value=hash_key_value(raw_key))
        self.client.logout()
        response = self.client.post(
            f"/api/one_time_secrets/{token}/reveal/", headers={"Authorization": f"Bearer {raw_key}"}
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
