from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("dashboards", "0015_dashboard_customization"),
    ]

    operations = [
        # The dropped index leads with (-pinned, name) and lists team_id last, so a team-scoped
        # list ordered by -pinned, name cannot seek it. Its deleted=false partial predicate is
        # not the blocker, because the list path excludes deleted rows anyway.
        SafeRemoveIndexConcurrently(
            model_name="dashboard",
            name="idx_dashboard_deleted_team_id",
        ),
        SafeAddIndexConcurrently(
            model_name="dashboard",
            index=models.Index(
                name="idx_dashboard_team_pinned_name",
                fields=["team", "-pinned", "name"],
            ),
        ),
    ]
