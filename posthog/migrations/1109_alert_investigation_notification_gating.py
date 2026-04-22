from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1108_alertcheck_investigation_verdict"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="investigation_gates_notifications",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="alertconfiguration",
            name="investigation_inconclusive_action",
            field=models.CharField(
                choices=[("notify", "Notify"), ("suppress", "Suppress")],
                default="notify",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="notification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="alertcheck",
            name="notification_suppressed_by_agent",
            field=models.BooleanField(default=False),
        ),
    ]
