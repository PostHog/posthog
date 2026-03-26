from django.db import migrations


class Migration(migrations.Migration):
    """Remove old TeamConversationsEmailConfig from Django state.

    The table is empty in production. This migration only removes the model
    from Django's state so that 0029 can safely DROP the table and recreate
    it with a UUID PK and ForeignKey to team.
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
