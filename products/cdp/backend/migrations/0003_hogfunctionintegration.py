import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("cdp", "0002_alter_hogfunction_batch_export"),
        ("posthog", "1251_alter_integration_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="HogFunctionIntegration",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "hog_function",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="integration_links",
                        to="cdp.hogfunction",
                    ),
                ),
                (
                    "integration",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hog_function_links",
                        to="posthog.integration",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="hogfunctionintegration",
            constraint=models.UniqueConstraint(
                fields=("hog_function", "integration"), name="unique_hog_function_integration"
            ),
        ),
    ]
