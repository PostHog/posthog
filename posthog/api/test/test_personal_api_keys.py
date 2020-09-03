from typing import Optional, Type

from posthog.models import PersonalAPIKey

from .base import TransactionBaseTest


class TestPersonalAPIKeysAPI(TransactionBaseTest):
    TESTS_API = True

    def setUp(self) -> None:
        super().setUp()
        self.personal_api_key = PersonalAPIKey.objects.create(label="Test", team=self.team, user=self.user)

    def test_create_personal_api_key(self):
        label = "Test key uno"
        response = self.client.post("/api/personal_api_keys/", {"label": label})
        self.assertEqual(response.status_code, 201)
        response_data = response.json()
        response_data.pop("created_at")
        key = PersonalAPIKey.objects.order_by("-created_at").first()
        assert key is not None  # for mypy
        self.assertDictEqual(
            response_data,
            {
                "id": key.id,
                "label": label,
                "last_used_at": None,
                "user_id": self.user.id,
                "team_id": self.team.id,
                "value": key.value,
            },
        )

    def test_create_personal_api_key_label_required(self):
        response = self.client.post("/api/personal_api_keys/", {"label": ""})
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertDictEqual(response_data, {"label": ["This field may not be blank."]})

    def test_delete_personal_api_key(self):
        self.assertEqual(PersonalAPIKey.objects.count(), 1)
        response = self.client.delete(f"/api/personal_api_keys/{self.personal_api_key.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(PersonalAPIKey.objects.count(), 0)

    def test_list_only_user_personal_api_keys(self):
        other_user = self._create_user("abc@def.xyz")
        other_key = PersonalAPIKey(label="Other test", team=self.team, user=other_user)
        other_key.save()
        self.assertEqual(PersonalAPIKey.objects.count(), 2)
        response = self.client.get("/api/personal_api_keys/")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        response_data[0].pop("created_at")
        self.assertDictEqual(
            response_data[0],
            {
                "id": self.personal_api_key.id,
                "label": self.personal_api_key.label,
                "last_used_at": None,
                "user_id": self.user.id,
                "team_id": self.team.id,
            },
        )

    def test_get_own_personal_api_key(self):
        response = self.client.get(f"/api/personal_api_keys/{self.personal_api_key.id}/")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        response_data.pop("created_at")
        self.assertDictEqual(
            response_data,
            {
                "id": self.personal_api_key.id,
                "label": self.personal_api_key.label,
                "last_used_at": None,
                "user_id": self.user.id,
                "team_id": self.team.id,
            },
        )

    def test_get_someone_elses_personal_api_key(self):
        other_user = self._create_user("abc@def.xyz")
        other_key = PersonalAPIKey(label="Other test", team=self.team, user=other_user)
        other_key.save()
        response = self.client.get(f"/api/personal_api_keys/{other_key.id}/")
        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertDictEqual(response_data, {"detail": "Not found."})


class TestPersonalAPIKeysAPIAuthentication(TransactionBaseTest):
    TESTS_API = True
    TESTS_FORCE_LOGIN = False

    def setUp(self) -> None:
        super().setUp()
        self.personal_api_key = PersonalAPIKey.objects.create(label="Test", team=self.team, user=self.user)

    def test_no_key(self):
        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 403)

    def test_header_resilience(self):
        response = self.client.get("/api/dashboard/", HTTP_AUTHORIZATION=f"Bearer  {self.personal_api_key.value}  ")
        self.assertEqual(response.status_code, 200)

    def test_query_string(self):
        response = self.client.get(f"/api/dashboard/?personal_api_key={self.personal_api_key.value}")
        self.assertEqual(response.status_code, 200)

    def test_body(self):
        response = self.client.get("/api/dashboard/", {"personal_api_key": self.personal_api_key.value})
        self.assertEqual(response.status_code, 200)

    def test_user_not_active(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.get("/api/user/", HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key.value}")
        self.assertEqual(response.status_code, 401)

    def test_user_endpoint(self):
        # special case as /api/user/ is (or used to be) uniquely not DRF (vanilla Django)
        response = self.client.get("/api/user/", HTTP_AUTHORIZATION=f"Bearer {self.personal_api_key.value}")
        self.assertEqual(response.status_code, 200)

    def test_capture(self):
        response = self.client.post(
            "/capture/",
            {"event": "x", "distinct_id": "y", "personal_api_key": self.personal_api_key.value},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_decide(self):
        response = self.client.get("/decide/", {"personal_api_key": self.personal_api_key.value})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["isAuthenticated"])
