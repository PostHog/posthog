import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0021_conversation_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="default_columns",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.TextField(), blank=True, null=True, size=None
            ),
        ),
    ]
