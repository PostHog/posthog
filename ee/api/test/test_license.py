import datetime
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from unittest.mock import Mock, patch

from django.utils import timezone
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from rest_framework import status

from posthog.models.organization import Organization
from posthog.models.team import Team

from ee.api.test.base import APILicensedTest
from ee.models.license import License


class TestLicenseAPI(APILicensedTest):
    @pytest.mark.skip_on_multitenancy
    def test_can_list_and_retrieve_licenses(self):
        response = self.client.get("/api/license")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["count"], 1)
        self.assertEqual(response_data["results"][0]["plan"], "enterprise")
        self.assertEqual(response_data["results"][0]["key"], "12345::67890")
        self.assertEqual(
            response_data["results"][0]["valid_until"],
            timezone.datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
        )

        retrieve_response = self.client.get(f"/api/license/{response_data['results'][0]['id']}")
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.json(), response_data["results"][0])

    @patch("ee.api.license.requests.post")
    @pytest.mark.skip_on_multitenancy
    def test_can_create_license(self, patch_post):
        valid_until = timezone.now() + datetime.timedelta(days=10)
        mock = Mock()
        mock.json.return_value = {
            "plan": "enterprise",
            "valid_until": valid_until.isoformat().replace("+00:00", "Z"),
        }
        patch_post.return_value = mock
        count = License.objects.count()

        response = self.client.post("/api/license", {"key": "newer_license_1"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json()
        self.assertEqual(response_data["plan"], "enterprise")
        self.assertEqual(response_data["key"], "newer_license_1")

        self.assertEqual(License.objects.count(), count + 1)
        license = License.objects.get(id=response_data["id"])
        self.assertEqual(license.key, "newer_license_1")
        self.assertEqual(license.valid_until, valid_until)

    @patch("ee.api.license.requests.post")
    @pytest.mark.skip_on_multitenancy
    def test_friendly_error_when_license_key_is_invalid(self, patch_post):
        mock = Mock()
        mock.ok = False
        mock.json.return_value = {
            "type": "validation_error",
            "code": "invalid_key",
            "detail": "Provided key is invalid.",
            "attr": "key",
        }
        patch_post.return_value = mock
        count = License.objects.count()

        response = self.client.post("/api/license", {"key": "invalid_key"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "license_error",
                "code": "invalid_key",
                "detail": "Provided key is invalid.",
                "attr": None,
            },
        )

        self.assertEqual(License.objects.count(), count)

    @pytest.mark.skip_on_multitenancy
    def test_highest_activated_license_is_used_after_upgrade(self):
        with freeze_time("2022-06-01T12:00:00.000Z"):
            License.objects.create(
                key="old",
                plan="scale",
                valid_until=timezone.datetime.now() + timezone.timedelta(days=30),
            )
        with freeze_time("2022-06-03T12:00:00.000Z"):
            License.objects.create(
                key="new",
                plan="enterprise",
                valid_until=timezone.datetime.now() + timezone.timedelta(days=30),
            )

        with freeze_time("2022-06-03T13:00:00.000Z"):
            first_valid = License.objects.first_valid()

            self.assertIsInstance(first_valid, License)
            self.assertEqual(first_valid.plan, "enterprise")  # type: ignore

    @pytest.mark.skip_on_multitenancy
    def test_highest_activated_license_is_used_after_renewal_to_lower(self):
        with freeze_time("2022-06-01T12:00:00.000Z"):
            License.objects.create(
                key="new",
                plan="enterprise",
                valid_until=timezone.datetime.now() + timezone.timedelta(days=30),
            )
        with freeze_time("2022-06-27T12:00:00.000Z"):
            License.objects.create(
                key="old",
                plan="scale",
                valid_until=timezone.datetime.now() + timezone.timedelta(days=30),
            )

        with freeze_time("2022-06-27T13:00:00.000Z"):
            first_valid = License.objects.first_valid()

            self.assertIsInstance(first_valid, License)
            self.assertEqual(first_valid.plan, "enterprise")  # type: ignore

    @pytest.mark.skip_on_multitenancy
    @patch("ee.api.license.requests.post")
    def test_can_cancel_license(self, patch_post):
        to_be_deleted = Team.objects.create(organization=self.organization)
        not_to_be_deleted = Team.objects.create(organization=self.organization, is_demo=True)  # don't delete
        other_org = Organization.objects.create()
        from_another_organisation = Team.objects.create(organization=other_org)

        self.assertEqual(Team.objects.count(), 4)
        self.assertEqual(
            sorted([team.id for team in Team.objects.all()]),
            sorted(
                [
                    self.team.pk,
                    to_be_deleted.pk,
                    not_to_be_deleted.pk,
                    from_another_organisation.pk,
                ]
            ),
        )

        mock = Mock()
        mock.json.return_value = {"ok": True}
        patch_post.return_value = mock
        response = self.client.delete(f"/api/license/{self.license.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(Team.objects.count(), 2)  # deleted two teams
        self.assertEqual(
            sorted([team.id for team in Team.objects.all()]),
            sorted([self.team.pk, not_to_be_deleted.pk]),
        )
        self.assertEqual(Organization.objects.count(), 1)

    @pytest.mark.skip_on_multitenancy
    @patch("ee.api.license.requests.post")
    def test_can_cancel_license_with_another_valid_license(self, patch_post):
        # In this case we won't delete projects as there's another valid license
        License.objects.create(valid_until=now() + relativedelta(years=1), plan="enterprise")
        Team.objects.create(organization=self.organization)
        Team.objects.create(organization=self.organization, is_demo=True)  # don't delete
        other_org = Organization.objects.create()
        Team.objects.create(organization=other_org)

        mock = Mock()
        mock.json.return_value = {"ok": True}
        patch_post.return_value = mock
        response = self.client.delete(f"/api/license/{self.license.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(Team.objects.count(), 4)
        self.assertEqual(Team.objects.all().order_by("pk")[0].pk, self.team.pk)
        self.assertEqual(Organization.objects.count(), 2)
