from django.db import migrations, models

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1239_migrate_approvals_models"),
    ]

    operations = [
        # Catalog connection moves onto DuckgresServer (the DuckLake catalog is a separate
        # Postgres store from the duckgres query server, so its connection is preserved).
        migrations.AddField(
            model_name="duckgresserver",
            name="catalog_host",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="duckgresserver",
            name="catalog_port",
            field=models.IntegerField(default=5432),
        ),
        migrations.AddField(
            model_name="duckgresserver",
            name="catalog_database",
            field=models.CharField(default="ducklake", max_length=255),
        ),
        migrations.AddField(
            model_name="duckgresserver",
            name="catalog_username",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="duckgresserver",
            name="catalog_password",
            field=posthog.helpers.encrypted_fields.EncryptedTextField(blank=True, max_length=500, null=True),
        ),
        # Backfill state moves onto DuckgresServerTeam (one row per team — the same row that
        # records the team's duckling membership).
        migrations.AddField(
            model_name="duckgresserverteam",
            name="backfill_enabled",
            field=models.BooleanField(default=True, help_text="Whether warehouse backfills are enabled for this team"),
        ),
        migrations.AddField(
            model_name="duckgresserverteam",
            name="table_suffix",
            field=models.CharField(
                blank=True,
                help_text="Suffix for this team's warehouse tables in the duckling (events_<suffix>, persons_<suffix>). "
                "User-supplied; falls back to the shared tables when unset.",
                max_length=63,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="duckgresserverteam",
            name="earliest_event_date",
            field=models.DateField(
                blank=True,
                help_text="Cached earliest event date (clamped to the backfill floor) used to size the historical "
                "backfill range. Populated lazily by the full-backfill sensor so it never re-queries ClickHouse; "
                "leave unset to have the sensor resolve and store it on its next tick.",
                null=True,
            ),
        ),
    ]
