from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [("data_quality", "0012_posthog_table_subject")]

    operations = [ValidateConstraint(model_name="dataqualitycheck", name="quality_check_subject_binding")]
