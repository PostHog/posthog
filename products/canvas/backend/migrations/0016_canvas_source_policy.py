from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="canvas",
            name="source_policy",
            field=models.CharField(db_default="standard", default="standard", max_length=32),
        ),
    ]
