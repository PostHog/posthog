from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1370_backfill_taggeditem_generic_pointer"),
    ]

    operations = [
        AddConstraintNotValid(
            model_name="taggeditem",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("content_type__isnull", False),
                    ("team__isnull", False),
                    models.Q(
                        models.Q(("object_id__isnull", False), ("object_uuid__isnull", True)),
                        models.Q(("object_id__isnull", True), ("object_uuid__isnull", False)),
                        _connector="OR",
                    ),
                ),
                name="taggeditem_generic_pointer_set",
            ),
        ),
    ]
