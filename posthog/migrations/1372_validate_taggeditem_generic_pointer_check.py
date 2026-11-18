from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1371_taggeditem_generic_pointer_check"),
    ]

    operations = [
        ValidateConstraint(model_name="taggeditem", name="taggeditem_generic_pointer_set"),
    ]
