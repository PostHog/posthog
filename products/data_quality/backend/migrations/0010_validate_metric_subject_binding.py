from django.db import migrations

from posthog.migration_helpers import ValidateConstraint


class Migration(migrations.Migration):
    dependencies = [("data_quality", "0009_metric_subject_and_check_schedules")]

    operations = [ValidateConstraint(model_name="dataqualitycheck", name="quality_check_subject_binding")]
