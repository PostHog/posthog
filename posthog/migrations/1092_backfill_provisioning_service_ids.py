from django.db import migrations

CACHE_PREFIX = "stripe_app_resource_service:"


def backfill_service_ids(apps, schema_editor):
    """Backfill TeamProvisioningConfig.service_id from Redis cache for existing provisioned teams."""
    try:
        from django.core.cache import cache

        TeamProvisioningConfig = apps.get_model("posthog", "TeamProvisioningConfig")
        Team = apps.get_model("posthog", "Team")

        for team in Team.objects.all().only("id"):
            cached_service_id = cache.get(f"{CACHE_PREFIX}{team.id}")
            if cached_service_id:
                TeamProvisioningConfig.objects.update_or_create(
                    team=team,
                    defaults={"service_id": cached_service_id},
                )
    except Exception:
        pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1091_team_provisioning_config"),
    ]

    operations = [
        migrations.RunPython(backfill_service_ids, migrations.RunPython.noop),
    ]
