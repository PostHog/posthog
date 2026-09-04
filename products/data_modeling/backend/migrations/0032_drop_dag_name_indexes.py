from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently

TABLE = "posthog_datamodelingdag"
# Django's own names for the pair it builds for `db_index=True` on a TextField: the btree, and the
# `text_pattern_ops` companion the Postgres schema editor adds beside it.
NAME_INDEX = "posthog_datamodelingdag_name_2014dd92"
LIKE_INDEX = f"{NAME_INDEX}_like"


class Migration(migrations.Migration):
    # Both indexes are dead. Every read of `name` filters by team first, so the
    # `name_unique_within_team` composite already covers it, and no caller does the prefix lookup
    # `text_pattern_ops` exists for — the searches on this column are `icontains`, a leading
    # wildcard. Dropping the pair removes their write cost on every DAG insert and rename.
    #
    # Neither index is in Django's migration state, because `db_index=True` builds them through the
    # schema editor rather than through an `AddIndex`. So the raw drop form is the one that applies,
    # and the state half is the `AlterField` that removes `db_index`.
    atomic = False

    dependencies = [
        ("data_modeling", "0031_datamodelingjob_run_mode"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="dag",
                    name="name",
                    field=models.TextField(max_length=2048),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name=NAME_INDEX,
                    table_name=TABLE,
                    columns="(name)",
                ),
                DropIndexConcurrently(
                    index_name=LIKE_INDEX,
                    table_name=TABLE,
                    columns="(name text_pattern_ops)",
                ),
            ],
        ),
    ]
