from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1315_githubinstallrequest_account")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="organizationdomain",
                    old_name="identity_provider_config",
                    new_name="_identity_provider_config",
                ),
                migrations.AlterField(
                    model_name="organizationdomain",
                    name="_identity_provider_config",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="identity_provider_config_id",
                        null=True,
                        on_delete=models.SET_NULL,
                        related_name="+",
                        to="posthog.identityproviderconfig",
                    ),
                ),
            ],
            database_operations=[],
        )
    ]
