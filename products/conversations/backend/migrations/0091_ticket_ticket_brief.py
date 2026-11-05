from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conversations", "0090_pylon_issue_uniq")]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="ticket_brief",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
