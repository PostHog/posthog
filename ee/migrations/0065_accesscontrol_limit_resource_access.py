from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0064_split_identity_provider_config_scopes"),
    ]

    operations = [
        migrations.AddField(
            model_name="accesscontrol",
            name="limit_resource_access",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
