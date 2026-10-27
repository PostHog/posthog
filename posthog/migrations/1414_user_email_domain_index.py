import django.db.models.functions.text
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    A lookup of users by email domain reads every row of posthog_user.

    The lookup filters on `EMAIL_DOMAIN_EXPRESSION`, which is `split_part(LOWER(email), '@', 2)`.
    No other index on posthog_user serves that expression. This index matches it, so the lookup
    becomes an index scan.

    posthog_user is a hot table, so the index builds with CREATE INDEX CONCURRENTLY via
    SafeAddIndexConcurrently. It takes a SHARE UPDATE EXCLUSIVE lock and does not block reads or writes.
    The index lands before any query uses it, so the build finishes before a lookup depends on it.
    """

    atomic = False

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("posthog", "1413_event_filter_pipeline_override"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="user",
            index=models.Index(
                models.Func(
                    django.db.models.functions.text.Lower("email"),
                    models.Value("@"),
                    models.Value(2),
                    function="split_part",
                    output_field=models.CharField(),
                ),
                name="user_email_domain_idx",
            ),
        ),
    ]
