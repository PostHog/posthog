from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestDebugCHQuery(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_denied(self):
        with patch("posthog.api.debug_ch_queries.is_cloud", return_value=True):
            with patch("posthog.api.debug_ch_queries.DEBUG", True):
                resp = self.client.get("/api/debug_ch_queries/")
                self.assertEqual(resp.status_code, HTTP_200_OK)

            with patch("posthog.api.debug_ch_queries.DEBUG", False):
                resp = self.client.get("/api/debug_ch_queries/")
                self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

            self.user.is_staff = True
            self.user.save()

            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)

        with patch("posthog.api.debug_ch_queries.is_cloud", return_value=False):
            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)

    def _create_pat(self, scopes: list[str]) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def test_slowest_queries_pat_requires_scope_and_staff(self):
        # Without the query_performance scope, even a staff user is rejected.
        self.user.is_staff = True
        self.user.save()
        token = self._create_pat(scopes=["experiment:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

    def test_slowest_queries_wildcard_pat_rejected(self):
        # A full-access (`*`) PAT must NOT satisfy the query_performance:read requirement —
        # this scope is INTERNAL and only programmatically-minted tokens carry it explicitly.
        self.user.is_staff = True
        self.user.save()
        token = self._create_pat(scopes=["*"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN, resp.content)

    def test_slowest_queries_pat_with_scope_but_non_staff_rejected(self):
        # Scope grants the PAT past the scope check; is_staff still gates the action.
        self.assertFalse(self.user.is_staff)
        token = self._create_pat(scopes=["query_performance:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

    @patch("posthog.api.debug_ch_queries.sync_execute", return_value=[])
    def test_slowest_queries_pat_with_scope_and_staff_allowed(self, _mock_execute):
        self.user.is_staff = True
        self.user.save()
        token = self._create_pat(scopes=["query_performance:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)
