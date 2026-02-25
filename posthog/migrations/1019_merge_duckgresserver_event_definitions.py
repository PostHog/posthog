from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1018_duckgresserver"),
        ("posthog", "1018_migrate_event_definition_models"),
    ]

    operations = []
