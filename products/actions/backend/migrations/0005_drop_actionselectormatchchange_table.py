from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    """Drop the table 0004 took out of Django state.

    0004 removed ActionSelectorMatchChange from state and dropped its foreign key to posthog_action,
    and kept the table so pods on the old release could still read it through a rolling deploy.
    Nothing reads it now.
    """

    dependencies = [
        ("actions", "0004_remove_actionselectormatchchange_state"),
    ]

    operations = [
        SafeDropTable("actions_actionselectormatchchange"),
    ]
