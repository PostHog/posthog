from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import hash_key_value, is_masked_value, mask_key_value


class TestIsMaskedValue(SimpleTestCase):
    @parameterized.expand(
        [
            ("dots_form", mask_key_value("phx_" + "a" * 40), True),
            ("short_token_fallback", "********", True),
            ("raw_token", "phx_" + "a" * 40, False),
            ("empty", "", False),
        ]
    )
    def test_shape(self, _name: str, value: str, expected: bool) -> None:
        self.assertEqual(is_masked_value(value), expected)


class TestMaskedKeyGuard(BaseTest):
    def _build(self, model: type, mask_value: str | None):
        if model is PersonalAPIKey:
            return model(user=self.user, label="k", mask_value=mask_value)
        return model(team=self.team, label="k", mask_value=mask_value)

    @parameterized.expand([("personal", PersonalAPIKey), ("project_secret", ProjectSecretAPIKey)])
    def test_raw_token_is_rejected(self, _name: str, model: type) -> None:
        token = "phx_" + "a" * 40
        key = self._build(model, mask_value=token)
        key.secure_value = hash_key_value(token)
        with self.assertRaises(ValueError):
            key.save()

    @parameterized.expand([("personal", PersonalAPIKey), ("project_secret", ProjectSecretAPIKey)])
    def test_set_mask_value_masks_and_saves(self, _name: str, model: type) -> None:
        token = "phx_" + "a" * 40
        key = self._build(model, mask_value=None)
        key.set_mask_value(token)
        key.secure_value = hash_key_value(token)
        key.save()
        key.refresh_from_db()
        self.assertEqual(key.mask_value, mask_key_value(token))
