from django.db import migrations, models
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    Case-insensitive email lookups scan the whole table.

    Django compiles `email__iexact=x` to `UPPER(email::text) = UPPER($1)`. Neither the plain
    unique btree on `posthog_user.email` nor `posthog_organizationinvite.target_email`'s btree
    serves that expression, so every login, password reset, invite check, and login precheck
    falls back to a sequential scan whose cost grows with the table.

    These expression indexes on `UPPER(email)` match what the ORM emits (Postgres normalizes
    both the query and the index expression to `upper((email)::text)`), so the lookups become
    index scans. posthog_user is a hot table, so both build with CREATE INDEX CONCURRENTLY via
    SafeAddIndexConcurrently, which takes a SHARE UPDATE EXCLUSIVE lock and does not block reads
    or writes.
    """

    atomic = False

    dependencies = [
        ("posthog", "1331_messagingrecord_campaign_key_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="user",
            index=models.Index(Upper("email"), name="posthog_user_upper_email_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="organizationinvite",
            index=models.Index(Upper("target_email"), name="orginvite_upper_email_idx"),
        ),
    ]
