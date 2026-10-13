from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    Every inbound Slack webhook resolves its PostHog project by (kind, integration_id), because the
    payload names the Slack workspace and nothing else. The only index covering those columns is the
    `posthog_integration_kind_id_unique` constraint, which leads with `team`, so that lookup can't
    use it.

    Built with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE) rather than a plain AddIndex, so
    reads and writes on posthog_integration keep running while it builds.
    """

    atomic = False

    dependencies = [("posthog", "1308_githubinstallrequest")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="integration",
            index=models.Index(fields=["kind", "integration_id"], name="posthog_integration_kind_ext"),
        ),
    ]
