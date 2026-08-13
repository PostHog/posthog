from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client

from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value


class TestPersonalAPIKeyAdmin(BaseTest):
    @patch("posthog.admin.admins.personal_api_key_admin.send_personal_api_key_exposed")
    def test_roll_rolls_key_and_notifies(self, mock_exposed: MagicMock):
        self.client = Client()
        self.client.force_login(self.user)
        self.user.is_staff = True
        self.user.save()

        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            user=self.user,
            label="Admin Key",
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
            scopes=["*"],
        )
        old_secure_value = key.secure_value
        old_mask_value = key.mask_value

        response = self.client.post(
            f"/admin/posthog/personalapikey/{key.pk}/roll/", data={"_roll_url": "https://github.com/some/leak"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/admin/posthog/personalapikey/{key.pk}/change/")

        key.refresh_from_db()
        self.assertNotEqual(key.secure_value, old_secure_value)
        self.assertIsNotNone(key.last_rolled_at)

        mock_exposed.assert_called_once_with(
            self.user.id, key.id, old_mask_value, "This key was detected at https://github.com/some/leak."
        )
