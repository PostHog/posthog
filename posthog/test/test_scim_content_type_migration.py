from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth.models import (
    Group as AuthGroup,
    Permission,
)
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase

from parameterized import parameterized

from posthog.models import User

scim_migration = import_module("posthog.migrations.1407_scimprovisioneduser_scimrequestlog")


class TestSCIMContentTypeMigration(TestCase):
    @parameterized.expand(["scimprovisioneduser", "scimrequestlog"])
    def test_duplicate_permissions_merge_grants(self, model_name: str) -> None:
        source, _ = ContentType.objects.get_or_create(app_label="ee", model=model_name)
        target, _ = ContentType.objects.get_or_create(app_label="posthog", model=model_name)
        codename = f"scim_migration_test_{model_name}"
        source_permission = Permission.objects.create(content_type=source, codename=codename, name="Source permission")
        target_permission = Permission.objects.create(content_type=target, codename=codename, name="Target permission")
        user = User.objects.create_user(email=f"{model_name}@example.com", password=None, first_name="SCIM")
        group = AuthGroup.objects.create(name=f"scim-migration-{model_name}")
        user.user_permissions.add(source_permission)
        group.permissions.add(target_permission)

        scim_migration.update_content_types(apps, SimpleNamespace(connection=connection))

        self.assertFalse(ContentType.objects.filter(pk=source.pk).exists())
        self.assertEqual(Permission.objects.filter(content_type=target, codename=codename).count(), 1)
        self.assertTrue(user.user_permissions.filter(content_type=target, codename=codename).exists())
        self.assertTrue(group.permissions.filter(content_type=target, codename=codename).exists())
