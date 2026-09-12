from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    The person deletion status endpoint scans the whole async deletion table.

    It filters posthog_asyncdeletion on team_id plus deletion_type, sorts by created_at, and
    paginates, which also issues a COUNT. The table has no index on team_id, so nothing serves
    the filter and nothing serves the sort. Both the scan and the COUNT get slower as the table
    grows with every queued person and team deletion.

    The index leads with the two equality columns and ends with the sort column, so the planner
    reads only the rows of one team instead of sorting the table.
    """

    atomic = False

    dependencies = [("posthog", "1352_email_lookup_indexes")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="asyncdeletion",
            index=models.Index(
                name="asyncdeletion_team_type_idx",
                fields=["team_id", "deletion_type", "-created_at"],
            ),
        ),
    ]
