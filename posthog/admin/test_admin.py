from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin import AdminSite

from posthog.admin import register_all_admin


class TestAdmin(BaseTest):
    def test_register_admin_models_succeeds(self):
        with patch.object(admin, "site", AdminSite()):
            register_all_admin()
