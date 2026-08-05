import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1227_alter_datadeletionrequest_delete_all_events")]

    operations = [
        migrations.AddField(
            model_name="teamprovisioningconfig",
            name="application",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="provisioned_team_configs",
                to=settings.OAUTH2_PROVIDER_APPLICATION_MODEL,
            ),
        ),
    ]
