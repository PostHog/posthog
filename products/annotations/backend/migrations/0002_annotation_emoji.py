from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("annotations", "0001_migrate_annotations_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="annotation",
            name="emoji",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
    ]
