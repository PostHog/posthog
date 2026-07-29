from django.db import migrations

CHUNK_SIZE = 200


def backfill_ai_observability_clusters_access_control(apps, schema_editor):
    # Clustering used to inherit its access level from llm_analytics; now that it's an
    # independent resource, mirror every resource-wide llm_analytics grant onto a matching
    # ai_observability_clusters row so existing permissions keep working instead of silently
    # defaulting to editor. Rows with a resource_id are per-object grants on other llm_analytics
    # sub-resources (datasets, evaluations, ...) and aren't clustering-related, so they're excluded.
    # Performance note: there are roughly 450 access control rows that will be filtered and created,
    # so this migration should be near-instant
    AccessControl = apps.get_model("ee", "AccessControl")

    for row in AccessControl.objects.filter(resource="llm_analytics", resource_id__isnull=True).iterator(
        chunk_size=CHUNK_SIZE
    ):
        AccessControl.objects.get_or_create(
            resource="ai_observability_clusters",
            resource_id=None,
            team_id=row.team_id,
            organization_member_id=row.organization_member_id,
            role_id=row.role_id,
            defaults={"access_level": row.access_level, "created_by_id": row.created_by_id},
        )


def reverse_func(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0050_migrate_replay_models"),
    ]

    operations = [
        migrations.RunPython(backfill_ai_observability_clusters_access_control, reverse_func),
    ]
