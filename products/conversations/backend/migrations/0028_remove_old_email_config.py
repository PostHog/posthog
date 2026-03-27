from django.db import migrations


class Migration(migrations.Migration):
    """Remove old TeamConversationsEmailConfig from Django state.

    The old table (posthog_conversations_email_config) stays in the DB and
    will be dropped in a follow-up PR. Migration 0029 creates a new
    EmailChannel model with a separate table.
    """

    dependencies = [
        ("conversations", "0027_slack_config_unique_slack_team_id"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="TeamConversationsEmailConfig"),
            ],
            database_operations=[],
        ),
    ]
