from django.db import migrations, models
from django.db.models.functions import Lower, Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    Case-insensitive email lookups scan the whole table.

    Login, password reset, and the login precheck resolve an address by its `LOWER()` fold.
    The invite lookups use `target_email__iexact`, which Django compiles to `UPPER()`. Neither
    the plain unique btree on `posthog_user.email` nor `posthog_organizationinvite`'s btree on
    `target_email` serves an expression, so each lookup falls back to a sequential scan whose
    cost grows with the table.

    Each index matches the expression its own callers emit, so those lookups become index scans.
    posthog_user is a hot table, so both build with CREATE INDEX CONCURRENTLY via
    SafeAddIndexConcurrently, which takes a SHARE UPDATE EXCLUSIVE lock and does not block reads
    or writes.
    """

    atomic = False

    dependencies = [("posthog", "1351_drop_persistedfolder_table")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="user",
            index=models.Index(Lower("email"), name="posthog_user_lower_email_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="organizationinvite",
            index=models.Index(Upper("target_email"), name="orginvite_upper_email_idx"),
        ),
    ]
