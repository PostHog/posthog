import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0867_add_updated_at_to_feature_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="notebook",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255), blank=True, default=list
            ),
        ),
    ]
