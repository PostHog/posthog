from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1164_alter_alertconfiguration_calculation_interval"),
    ]

    # SeparateDatabaseAndState: Django's auto-generated SQL for AddField with default=
    # adds the column with a DEFAULT then immediately runs ALTER COLUMN ... DROP DEFAULT,
    # because Django treats `default=` as a Python-only concern. posthog_user has
    # non-Django writers (rust/, nodejs/), so we keep the Postgres-level default to
    # avoid breaking raw INSERTs that omit this column.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="user",
                    name="hide_mcp_hints",
                    field=models.BooleanField(
                        blank=False,
                        default=False,
                        help_text="When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.",
                        null=False,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_user" ADD COLUMN "hide_mcp_hints" boolean DEFAULT false NOT NULL;',
                    reverse_sql='ALTER TABLE "posthog_user" DROP COLUMN "hide_mcp_hints";',
                ),
            ],
        ),
    ]
