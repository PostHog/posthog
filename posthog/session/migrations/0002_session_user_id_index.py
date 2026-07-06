from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Built concurrently (and in its own
    # migration, per PostHog policy) so adopting the existing, every-request-written django_session
    # table never takes a blocking lock on a large table.
    atomic = False

    dependencies = [("posthog_session", "0001_initial")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="session",
            index=models.Index(fields=["user_id"], name="django_session_user_id_idx"),
        ),
    ]
