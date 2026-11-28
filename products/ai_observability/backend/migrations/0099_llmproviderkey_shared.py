from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0098_retire_evaluation_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmproviderkey",
            name="shared",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
