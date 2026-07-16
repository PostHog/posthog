from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0021_add_zeabur_provider")]

    operations = [
        migrations.AlterField(
            model_name="evaluationreportrun",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("generated", "Generated"),
                    ("delivered", "Delivered"),
                    ("partial_failure", "Partial Failure"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
