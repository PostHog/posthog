import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1036_experiment_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="integration",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="posthog.integration",
            ),
        ),
    ]
