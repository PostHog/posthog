from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0040_ticket_ai_triage"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="organization_id",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
