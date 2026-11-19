from django.db import migrations

CHUNK_SIZE = 200


def backfill_marketing_analytics_access_control(apps, schema_editor):
    # Marketing analytics used to inherit its access level from web_analytics; now that it's an
    # independent resource, mirror every resource-wide web_analytics grant onto a matching
    # marketing_analytics row so existing permissions keep working instead of silently defaulting
    # to editor. Rows with a resource_id are per-object grants and were never part of marketing
    # analytics' access resolution, so they're excluded.
    AccessControl = apps.get_model("ee", "AccessControl")

    # `marketing_analytics` was already a valid resource choice while it inherited from
    # web_analytics, so stray resource-wide rows may exist that nothing ever read. They are
    # removed first so the result mirrors web_analytics exactly instead of keeping a stale level
    # or making an orphan row live.
    AccessControl.objects.filter(resource="marketing_analytics", resource_id__isnull=True).delete()

    for row in AccessControl.objects.filter(resource="web_analytics", resource_id__isnull=True).iterator(
        chunk_size=CHUNK_SIZE
    ):
        AccessControl.objects.create(
            resource="marketing_analytics",
            resource_id=None,
            team_id=row.team_id,
            organization_member_id=row.organization_member_id,
            role_id=row.role_id,
            access_level=row.access_level,
            created_by_id=row.created_by_id,
        )


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access_control", "0003_teamaccesscontrolconfig"),
        ("ee", "0067_remove_scimrequestlog_identity_provider_config_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_marketing_analytics_access_control, reverse_func),
    ]
