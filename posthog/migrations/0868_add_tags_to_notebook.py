import django.contrib.postgres.fields
from django.db import migrations, models


def set_empty_tags(apps, _schema_editor):
    Notebook = apps.get_model("posthog", "Notebook")
    Notebook.objects.filter(tags__isnull=True).update(tags=[])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0867_add_updated_at_to_feature_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="notebook",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255), blank=True, null=True, default=list
            ),
        ),
        migrations.RunPython(set_empty_tags, reverse_code=migrations.RunPython.noop, elidable=True),
        migrations.AlterField(
            model_name="notebook",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255), blank=True, default=list
            ),
        ),
    ]
