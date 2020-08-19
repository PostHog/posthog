from typing import Type

from posthog.models import PersonalAPIKey

from .base import TransactionBaseTest


class TestPersonalAPIKeysAPI(TransactionBaseTest):
    TESTS_API = True

    def test_create_personal_api_key(self):
        label = "Test key uno"
        response = self.client.post("/api/personal_api_keys/", {"label": label})
        self.assertEqual(response.status_code, 201)
        key: Optional[PersonalAPIKey] = PersonalAPIKey.objects.first()
        response_data = response.json()
        response_data.pop("created_at")
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
        key = PersonalAPIKey(label="Test", team=self.team, user=self.user)
        key.save()
        self.assertEqual(len(PersonalAPIKey.objects.all()), 1)
        response = self.client.delete(f"/api/personal_api_keys/{key.id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(PersonalAPIKey.objects.all()), 1)

    def test_list_only_user_personal_api_keys(self):
        my_label = "Test"
        my_key = PersonalAPIKey(label=my_label, team=self.team, user=self.user)
        my_key.save()
        other_user = self._create_user("abc@def.xyz")
        other_key = PersonalAPIKey(label="Other test", team=self.team, user=other_user)
        other_key.save()
        self.assertEqual(len(PersonalAPIKey.objects.all()), 2)
        response = self.client.get("/api/personal_api_keys/")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        response_data[0].pop("created_at")
        self.assertDictEqual(
            response_data[0],
            {
                "id": my_key.id,
                "label": my_label,
                "last_used_at": None,
                "user_id": self.user.id,
                "team_id": self.team.id,
            },
        )

    def test_get_own_personal_api_key(self):
        my_label = "Test"
        my_key = PersonalAPIKey(label=my_label, team=self.team, user=self.user)
        my_key.save()
        response = self.client.get(f"/api/personal_api_keys/{my_key.id}/")
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        response_data.pop("created_at")
        self.assertDictEqual(
            response_data,
            {
                "id": my_key.id,
                "label": my_label,
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

    def test_no_key(self):
        response = self.client.get("/api/dashboard/")
        self.assertEqual(response.status_code, 403)

    def test_header_resilient(self):
        key = PersonalAPIKey(label="Test", team=self.team, user=self.user)
        key.save()
        response = self.client.get("/api/dashboard/", HTTP_AUTHORIZATION=f"Bearer  {key.value}  ")
        self.assertEqual(response.status_code, 200)

    def test_query_string(self):
        key = PersonalAPIKey(label="Test", team=self.team, user=self.user)
        key.save()
        response = self.client.get(f"/api/dashboard/?personal_api_key={key.value}")
        self.assertEqual(response.status_code, 200)

    def test_body(self):
        key = PersonalAPIKey(label="Test", team=self.team, user=self.user)
        key.save()
        response = self.client.get("/api/dashboard/", {"personal_api_key": key.value})
        self.assertEqual(response.status_code, 200)

    def test_user_endpoint(self):
        # special case as /api/user/ is (or used to be) uniquely not DRF (vanilla Django)
        key = PersonalAPIKey(label="Test", team=self.team, user=self.user)
        key.save()
        response = self.client.get("/api/user/", HTTP_AUTHORIZATION=f"Bearer {key.value}")
        self.assertEqual(response.status_code, 200)
