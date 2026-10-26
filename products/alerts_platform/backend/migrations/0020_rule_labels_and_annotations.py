from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("alerts_platform", "0019_overflow_and_instance_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformalertconfiguration",
            name="annotations",
            field=models.JSONField(db_default={}, default=dict),
        ),
        migrations.AddField(
            model_name="platformalertconfiguration",
            name="labels",
            field=models.JSONField(db_default={}, default=dict),
        ),
    ]
