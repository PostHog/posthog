from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0069_ticket_compose_dedupe_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="awaiting_deletion_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="awaiting_deletion_linked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
