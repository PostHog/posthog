from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0026_account_slack_summary_cadence_accountchannelsummary"),
    ]

    operations = [
        ValidateForeignKey(model_name="accountchannelsummary", name="ca_channel_summary_team_id_fk"),
    ]
