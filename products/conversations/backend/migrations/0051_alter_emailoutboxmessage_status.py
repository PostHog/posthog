from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0050_alter_ticket_priority"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emailoutboxmessage",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sent", "Sent"),
                    ("failed_permanent", "Failed (permanent)"),
                    ("bounced", "Bounced"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
