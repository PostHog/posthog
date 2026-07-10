from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0021_add_zeabur_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmprompt",
            name="config",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="llmprompt",
            name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
