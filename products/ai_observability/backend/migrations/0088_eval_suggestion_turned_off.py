from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0087_offline_item_revision_floor"),
    ]

    operations = [
        migrations.AddField(
            model_name="evalsuggestionteamstate",
            name="turned_off_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
