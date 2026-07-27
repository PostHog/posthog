from django.db import migrations, models

import posthog.schema


class Migration(migrations.Migration):
    dependencies = [("posthog", "1163_alter_batchexportrun_batch_export_and_more")]

    operations = [
        migrations.AlterField(
            model_name="alertconfiguration",
            name="calculation_interval",
            field=models.CharField(
                blank=True,
                choices=[
                    (posthog.schema.AlertCalculationInterval["EVERY_15_MINUTES"], "every_15_minutes"),
                    (posthog.schema.AlertCalculationInterval["HOURLY"], "hourly"),
                    (posthog.schema.AlertCalculationInterval["DAILY"], "daily"),
                    (posthog.schema.AlertCalculationInterval["WEEKLY"], "weekly"),
                    (posthog.schema.AlertCalculationInterval["MONTHLY"], "monthly"),
                ],
                default=posthog.schema.AlertCalculationInterval["DAILY"],
                max_length=20,
                null=True,
            ),
        ),
    ]
