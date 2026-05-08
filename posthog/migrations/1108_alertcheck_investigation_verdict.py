from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1107_alertcheck_investigation_summary")]

    operations = [
        migrations.AddField(
            model_name="alertcheck",
            name="investigation_verdict",
            field=models.CharField(
                blank=True,
                choices=[
                    ("true_positive", "true_positive"),
                    ("false_positive", "false_positive"),
                    ("inconclusive", "inconclusive"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
