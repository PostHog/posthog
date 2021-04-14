import datetime
from unittest.mock import Mock, patch

import pytz
from django.utils import timezone
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.license import License


class TestLicenseAPI(APILicensedTest):
    def test_can_list_and_retrieve_licenses(self):
        response = self.client.get("/api/license")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["count"], 1)
        self.assertEqual(response_data["results"][0]["plan"], "enterprise")
        self.assertEqual(response_data["results"][0]["key"], "enterprise")
        self.assertEqual(
            response_data["results"][0]["valid_until"],
            timezone.datetime(2038, 1, 19, 3, 14, 7, tzinfo=pytz.UTC).isoformat().replace("+00:00", "Z"),
        )

        retrieve_response = self.client.get(f"/api/license/{response_data['results'][0]['id']}")
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.json(), response_data["results"][0])

    @patch("ee.models.license.requests.post")
    def test_can_create_license(self, patch_post):

        valid_until = timezone.now() + datetime.timedelta(days=10)
        mock = Mock()
        mock.json.return_value = {
            "plan": "enterprise",
            "valid_until": valid_until.isoformat().replace("+00:00", "Z"),
            "max_users": 10,
        }
        patch_post.return_value = mock
        count = License.objects.count()

        response = self.client.post("/api/license", {"key": "newer_license_1"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["plan"], "enterprise")
        self.assertEqual(response_data["key"], "newer_license_1")
        self.assertEqual(response_data["max_users"], 10)

        self.assertEqual(License.objects.count(), count + 1)
        license = License.objects.get(id=response_data["id"])
        self.assertEqual(license.key, "newer_license_1")
        self.assertEqual(license.valid_until, valid_until)
