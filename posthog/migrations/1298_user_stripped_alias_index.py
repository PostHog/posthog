import django.db.models.functions.text
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """
    posthog_user is a hot table read on virtually every request, so a plain `AddIndex` (which
    takes an ACCESS EXCLUSIVE lock to build) risks stalling site-wide traffic. SafeAddIndexConcurrently
    builds it with CREATE INDEX CONCURRENTLY (SHARE UPDATE EXCLUSIVE, doesn't block reads/writes),
    tracking Django state the same way AddIndex would.

    The index is not yet used by any query in this migration — EmailValidationHelper.user_exists_with_stripped_alias
    still filters via iexact/istartswith/iendswith. A follow-up change rewrites that lookup to filter
    on this same expression, turning its full-table scan into an index scan. Landing the index first,
    on its own, lets it finish building before that lookup starts relying on it.
    """

    atomic = False

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("posthog", "1297_add_instagram_integration_kind"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="user",
            index=models.Index(
                models.Func(
                    django.db.models.functions.text.Lower("email"),
                    models.Value("\\+[^@]*@"),
                    models.Value("@"),
                    function="regexp_replace",
                ),
                name="user_stripped_alias_idx",
            ),
        ),
    ]
