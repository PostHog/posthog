from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    The nightly OAuth cleanup job selects ID tokens that expired before the retention cutoff and
    have no access token. The table carries no index on `expires`, so that anti-join reads the
    whole table once per batch it deletes, and the cost grows with the backlog of expired tokens.
    Built concurrently (SHARE UPDATE EXCLUSIVE) so the build does not block reads or writes on the
    token endpoint.
    """

    atomic = False

    dependencies = [
        ("posthog", "1374_teamheatmapconfig_capture_enforcement_started_at_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="oauthidtoken",
            index=models.Index(fields=["expires"], name="oauthidtoken_expires_idx"),
        ),
    ]
