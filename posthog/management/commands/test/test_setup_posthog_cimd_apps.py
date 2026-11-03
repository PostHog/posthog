from io import StringIO

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from posthog.management.commands.setup_posthog_cimd_apps import POSTHOG_CIMD_DOCUMENTS
from posthog.models import OAuthApplication

HOG_CLIENT_ID = "https://posthog.com/.well-known/oauth/hog/client-metadata.json"
CLIENT_IDS = sorted(str(document["client_id"]) for document in POSTHOG_CIMD_DOCUMENTS)


class TestSetupPostHogCIMDApps(TestCase):
    def test_every_posthog_cimd_app_is_created_verified_and_a_rerun_verifies_an_existing_one(self) -> None:
        call_command("setup_posthog_cimd_apps", stdout=StringIO())
        OAuthApplication.objects.filter(client_id=HOG_CLIENT_ID).update(is_verified=False)

        call_command("setup_posthog_cimd_apps", stdout=StringIO())

        apps = OAuthApplication.objects.filter(client_id__in=CLIENT_IDS).order_by("client_id")
        self.assertEqual([app.client_id for app in apps], CLIENT_IDS)
        self.assertTrue(all(app.is_verified and app.is_cimd_client for app in apps))
        hog = apps.get(client_id=HOG_CLIENT_ID)
        self.assertEqual(hog.authorization_grant_type, OAuthApplication.GRANT_DEVICE_CODE)

    @patch("posthog.management.commands.setup_posthog_cimd_apps.get_instance_region", return_value="US")
    def test_a_production_region_is_left_alone(self, _region) -> None:
        call_command("setup_posthog_cimd_apps", stdout=StringIO())

        self.assertFalse(OAuthApplication.objects.filter(client_id__in=CLIENT_IDS).exists())
