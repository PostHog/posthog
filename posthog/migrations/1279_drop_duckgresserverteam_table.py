from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1278_identityproviderconfig_config_scope_and_more"),
    ]

    operations = [
        # Second step of the DuckgresServerTeam retirement: migration 1265 removed the
        # model from Django state (per-team managed-warehouse state now lives in the
        # duckgres control plane), and that change has been deployed for a full cycle
        # with every environment reading the control plane. Drop the orphaned table,
        # including its stale rows for organizations whose warehouses no longer exist.
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_duckgresserverteam;",
            reverse_sql="",  # No reverse - the table is obsolete and its data superseded
        ),
    ]
