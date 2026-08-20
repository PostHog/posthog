from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1310_provisioning_rate_limit_overrides")]

    operations = [
        migrations.AddField(
            model_name="oauthaccesstoken",
            name="sandbox_workload",
            field=models.CharField(blank=True, max_length=32, null=True),
        )
    ]
