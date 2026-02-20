from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1015_normalize_feature_flag_payloads_to_strings"),
    ]

    operations = [
        migrations.AddField(
            model_name="schemapropertygroupproperty",
            name="is_optional_in_types",
            field=models.BooleanField(default=False),
        ),
    ]
