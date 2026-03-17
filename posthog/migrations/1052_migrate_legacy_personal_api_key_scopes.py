from django.db import migrations


def migrate_legacy_scopes(apps, schema_editor):
    PersonalAPIKey = apps.get_model("posthog", "PersonalAPIKey")
    PersonalAPIKey.objects.filter(scopes__isnull=True).update(scopes=["*"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1051_backfill_holdout_format"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_scopes, migrations.RunPython.noop, elidable=True),
    ]
