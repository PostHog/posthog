from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1014_increase_annotation_content_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="schemapropertygroupproperty",
            name="is_optional_in_types",
            field=models.BooleanField(default=False),
        ),
    ]
