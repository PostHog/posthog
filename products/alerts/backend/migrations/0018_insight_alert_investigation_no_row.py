import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0017_squash_2026_11_02_finalize_fks"),
    ]

    operations = [
        migrations.AlterField(
            model_name="insightalertinvestigation",
            name="alert_configuration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="alerts.alertconfiguration",
            ),
        ),
    ]
