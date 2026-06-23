from posthog.test.base import BaseTest

from posthog.models.project_secret_api_key import ProjectSecretAPIKey, find_project_secret_api_key
from posthog.models.utils import hash_key_value


class TestFindProjectSecretAPIKey(BaseTest):
    def test_match(self):
        token = "phs_" + "m" * 35
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="lookup",
            secure_value=hash_key_value(token),
            scopes=["endpoint:read"],
        )

        found = find_project_secret_api_key(token)
        assert found is not None
        self.assertEqual(found.pk, psak.pk)

    def test_no_match(self):
        self.assertIsNone(find_project_secret_api_key("phs_" + "q" * 35))

    def test_hash_isolation(self):
        token_a = "phs_" + "a" * 35
        token_b = "phs_" + "b" * 35
        psak_a = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="a",
            secure_value=hash_key_value(token_a),
        )

        found = find_project_secret_api_key(token_a)
        assert found is not None
        self.assertEqual(found.pk, psak_a.pk)

        self.assertIsNone(find_project_secret_api_key(token_b))
