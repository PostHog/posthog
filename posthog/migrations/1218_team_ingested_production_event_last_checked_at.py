from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1217_project_is_pending_deletion"),
    ]

    # Additive, metadata-only. Nullable timestamp — no Postgres-level DEFAULT needed
    # because INSERTs that omit the column get NULL automatically. The daily sweep
    # stamps it via the ORM; existing rows start NULL until first checked.
    operations = [
        migrations.AddField(
            model_name="team",
            name="ingested_production_event_last_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
