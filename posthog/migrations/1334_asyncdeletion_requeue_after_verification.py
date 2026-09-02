from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, DropIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1333_uploaded_media_library_index"),
    ]

    # The replacements are created before the originals are dropped, so no window exists in which
    # duplicate pending requests can land.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="asyncdeletion",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("delete_verified_at__isnull", True), ("group_type_index__isnull", True)),
                        fields=("deletion_type", "key"),
                        name="unique pending deletion",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique pending deletion",
                    table_name="posthog_asyncdeletion",
                    columns='("deletion_type", "key")',
                    unique=True,
                    where='WHERE ("delete_verified_at" IS NULL AND "group_type_index" IS NULL)',
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="asyncdeletion",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("delete_verified_at__isnull", True)),
                        fields=("deletion_type", "key", "group_type_index"),
                        name="unique pending deletion for groups",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique pending deletion for groups",
                    table_name="posthog_asyncdeletion",
                    columns='("deletion_type", "key", "group_type_index")',
                    unique=True,
                    where='WHERE "delete_verified_at" IS NULL',
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(model_name="asyncdeletion", name="unique deletion"),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="unique deletion",
                    table_name="posthog_asyncdeletion",
                    columns='("deletion_type", "key")',
                    unique=True,
                    where='WHERE "group_type_index" IS NULL',
                ),
            ],
        ),
        # Declared without a condition, so Postgres holds this one as a table constraint rather
        # than a bare index. Dropping it is a metadata change; there is no concurrent form.
        migrations.RemoveConstraint(model_name="asyncdeletion", name="unique deletion for groups"),
    ]
