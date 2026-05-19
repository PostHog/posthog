from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1164_alter_alertconfiguration_calculation_interval"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="hide_mcp_hints",
            field=models.BooleanField(
                blank=True,
                default=False,
                help_text="When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions.",
                null=True,
            ),
        ),
    ]
