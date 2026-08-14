import importlib
from collections.abc import Collection
from types import SimpleNamespace

import pytest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

migration = importlib.import_module("posthog.migrations.1281_migrate_managed_warehouse_models")


def _assert_assignments(
    permission: Permission,
    *,
    user_ids: Collection[object],
    group_ids: Collection[object],
) -> None:
    User = get_user_model()
    assert set(User.objects.filter(user_permissions=permission).values_list("id", flat=True)) == user_ids
    assert set(Group.objects.filter(permissions=permission).values_list("id", flat=True)) == group_ids


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", migration.MODELS_TO_COPY)
def test_content_type_copy_preserves_grants_across_forward_reverse_and_reapply(model_name: str) -> None:
    migration_apps = (
        MigrationExecutor(connection).loader.project_state([("posthog", "1281_migrate_managed_warehouse_models")]).apps
    )
    source_content_type, _ = ContentType.objects.get_or_create(app_label="posthog", model=model_name)
    target_content_type, _ = ContentType.objects.get_or_create(app_label="managed_warehouse", model=model_name)

    source_only = Permission.objects.create(
        content_type=source_content_type,
        codename=f"migration_source_only_{model_name}",
        name="Source-only migration permission",
    )
    source_shared = Permission.objects.create(
        content_type=source_content_type,
        codename=f"migration_shared_{model_name}",
        name="Shared migration permission",
    )
    target_shared = Permission.objects.create(
        content_type=target_content_type,
        codename=source_shared.codename,
        name=source_shared.name,
    )
    target_only = Permission.objects.create(
        content_type=target_content_type,
        codename=f"migration_target_only_{model_name}",
        name="Target-only migration permission",
    )

    User = get_user_model()
    source_user = User.objects.create(
        email=f"source-{model_name}@example.com",
        distinct_id=f"source-{model_name}",
    )
    target_user = User.objects.create(
        email=f"target-{model_name}@example.com",
        distinct_id=f"target-{model_name}",
    )
    source_group = Group.objects.create(name=f"source-{model_name}")
    target_group = Group.objects.create(name=f"target-{model_name}")

    source_user.user_permissions.add(source_only, source_shared)
    source_group.permissions.add(source_only, source_shared)
    target_user.user_permissions.add(target_shared, target_only)
    target_group.permissions.add(target_shared, target_only)

    schema_editor = SimpleNamespace(connection=connection)
    migration.update_content_types(migration_apps, schema_editor)

    assert ContentType.objects.filter(pk=source_content_type.pk).exists()
    assert ContentType.objects.filter(pk=target_content_type.pk).exists()
    copied_source_only = Permission.objects.get(
        content_type=target_content_type,
        codename=source_only.codename,
    )
    target_shared.refresh_from_db()
    _assert_assignments(
        copied_source_only,
        user_ids={source_user.pk},
        group_ids={source_group.pk},
    )
    _assert_assignments(
        target_shared,
        user_ids={source_user.pk, target_user.pk},
        group_ids={source_group.pk, target_group.pk},
    )

    migration.reverse_content_types(migration_apps, schema_editor)

    source_shared.refresh_from_db()
    copied_target_only = Permission.objects.get(
        content_type=source_content_type,
        codename=target_only.codename,
    )
    _assert_assignments(
        source_shared,
        user_ids={source_user.pk, target_user.pk},
        group_ids={source_group.pk, target_group.pk},
    )
    _assert_assignments(
        copied_target_only,
        user_ids={target_user.pk},
        group_ids={target_group.pk},
    )

    migration.update_content_types(migration_apps, schema_editor)

    assert Permission.objects.filter(content_type=source_content_type, codename=source_shared.codename).count() == 1
    assert Permission.objects.filter(content_type=target_content_type, codename=source_shared.codename).count() == 1
    target_shared.refresh_from_db()
    _assert_assignments(
        target_shared,
        user_ids={source_user.pk, target_user.pk},
        group_ids={source_group.pk, target_group.pk},
    )
