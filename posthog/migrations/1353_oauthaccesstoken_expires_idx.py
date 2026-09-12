from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    The nightly OAuth cleanup job selects access tokens that expired before the retention cutoff
    and have no refresh token. The table carries only a scopes GIN index and a btree on `token`,
    so that anti-join reads the whole table once per batch it deletes, and the cost grows with the
    backlog of expired tokens. Built concurrently (SHARE UPDATE EXCLUSIVE) so the build does not
    block reads or writes on the token endpoint.
    """

    atomic = False

    dependencies = [("posthog", "1352_email_lookup_indexes")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="oauthaccesstoken",
            index=models.Index(fields=["expires"], name="oauthaccesstoken_expires_idx"),
        ),
    ]
