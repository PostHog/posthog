from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0067_remove_scimrequestlog_identity_provider_config_and_more"),
    ]

    operations = [
        # auto_now has no database counterpart, so the columns do not change.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="enterpriseeventdefinition",
                    name="updated_at",
                    field=models.DateTimeField(blank=True, editable=False),
                ),
                migrations.AlterField(
                    model_name="enterprisepropertydefinition",
                    name="updated_at",
                    field=models.DateTimeField(blank=True, editable=False),
                ),
            ],
            database_operations=[],
        ),
    ]
