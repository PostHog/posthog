from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently

TABLE = "posthog_identityproviderconfig"
# Django's own names for the indexes behind `unique=True` on a varchar field, so the schema matches
# what it would have built and no later migration sees drift.
UNIQUE_INDEX = "posthog_identityproviderconfig_saml_relay_state_a35fb61b_uniq"
LIKE_INDEX = "posthog_identityproviderconfig_saml_relay_state_a35fb61b_like"


class Migration(migrations.Migration):
    # Named for the AlterField it started life as; that state change now lands in 1300, and this
    # builds the indexes behind it. Renaming the file would strand every database that has already
    # applied it, so the name stays.
    # `saml_relay_state` routes SAML logins, so this table is read on the auth path. Django's
    # AlterField would build both indexes under ACCESS EXCLUSIVE, and every read arriving behind it
    # would wait; CONCURRENTLY takes SHARE UPDATE EXCLUSIVE, which blocks neither. 1300 then
    # promotes the unique index to the constraint in a single catalog update.
    atomic = False

    dependencies = [
        ("posthog", "1298_user_stripped_alias_index"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name=UNIQUE_INDEX,
            table_name=TABLE,
            columns="(saml_relay_state)",
            unique=True,
        ),
        CreateIndexConcurrently(
            index_name=LIKE_INDEX,
            table_name=TABLE,
            columns="(saml_relay_state varchar_pattern_ops)",
        ),
    ]
