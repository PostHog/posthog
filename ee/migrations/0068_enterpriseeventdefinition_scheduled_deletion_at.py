from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0067_remove_scimrequestlog_identity_provider_config_and_more"),
        ("event_definitions", "0015_drop_index_property_def_query"),
    ]

    operations = [
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="scheduled_deletion_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="ingestion_stopped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
