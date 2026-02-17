from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1012_eventschema_enforcement_mode_idx"),
    ]

    operations = [
        migrations.RunSQL(
            # Ensure the DB itself enforces the default for non-Django writers
            # (e.g. property-defs-rs). See: https://github.com/PostHog/posthog/pull/46104
            sql="ALTER TABLE posthog_eventdefinition ALTER COLUMN enforcement_mode SET DEFAULT 'allow'",
            reverse_sql="ALTER TABLE posthog_eventdefinition ALTER COLUMN enforcement_mode DROP DEFAULT",
        ),
    ]
