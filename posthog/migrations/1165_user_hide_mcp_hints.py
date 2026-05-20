from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1164_alter_alertconfiguration_calculation_interval"),
    ]

    # db_default keeps the Postgres-level DEFAULT (Django would otherwise emit
    # `ALTER COLUMN ... DROP DEFAULT` right after ADD COLUMN, because it treats
    # plain `default=` as a Python-only concern). The DB default matters because
    # (a) posthog_user has non-Django writers in rust/ and nodejs/ that INSERT
    # without listing this column, and (b) the test DB is created from model
    # definitions (see posthog/management/commands/setup_test_environment.py
    # disable_migrations), so without db_default the CREATE TABLE in tests
    # would omit the default entirely and break those writers.
    operations = [
        migrations.AddField(
            model_name="user",
            name="hide_mcp_hints",
            field=models.BooleanField(
                blank=False,
                db_default=False,
                default=False,
                help_text="When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.",
                null=False,
            ),
        ),
    ]
