from django.db import migrations, models
from django.db.models.functions import Cast

from posthog.migration_helpers import CreateIndexConcurrently, SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("posthog", "1372_validate_taggeditem_generic_pointer_check"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("object_id__isnull", False)),
                        fields=("content_type", "object_id", "tag"),
                        name="unique_taggeditem_object_id",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_taggeditem_object_id",
                    table_name="posthog_taggeditem",
                    columns='("content_type_id", "object_id", "tag_id")',
                    unique=True,
                    where='WHERE "object_id" IS NOT NULL',
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(("object_uuid__isnull", False)),
                        fields=("content_type", "object_uuid", "tag"),
                        name="unique_taggeditem_object_uuid",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_taggeditem_object_uuid",
                    table_name="posthog_taggeditem",
                    columns='("content_type_id", "object_uuid", "tag_id")',
                    unique=True,
                    where='WHERE "object_uuid" IS NOT NULL',
                ),
            ],
        ),
        SafeAddIndexConcurrently(
            model_name="taggeditem",
            index=models.Index(
                models.F("content_type"),
                Cast("object_id", output_field=models.BigIntegerField()),
                condition=models.Q(("object_id__isnull", False)),
                name="taggeditem_object_id_bigint",
            ),
        ),
    ]
