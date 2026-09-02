from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0039_dataset_item_version_ownership_constraints"),
    ]

    operations = [
        ValidateForeignKey(model_name="datasetitemversion", name="llma_item_ver_item_owner_fk"),
        ValidateForeignKey(model_name="datasetitemversion", name="llma_item_ver_revision_owner_fk"),
    ]
