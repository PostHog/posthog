import django.contrib.postgres.fields
import structlog
from django.db import migrations, models


# Just copies the values of app_urls to recording_domains
def backfill_recording_domains(apps, _):
    # TODO: flip URLs into being domains
    logger = structlog.get_logger(__name__)
    logger.info("starting 0258_team_recording_domains")
    Team = apps.get_model("posthog", "Team")
    Team.objects.all().update(recording_domains=models.F("app_urls"))


# Because of the nature of this backfill, there's no way to reverse it without potentially destroying customer data
# However, we still need a reverse function, so that we can rollback other migrations
def reverse(apps, _):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0257_add_default_checked_for_test_filters_on_team"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="recording_domains",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=200, null=True), blank=True, default=list, size=None
            ),
        ),
        migrations.RunPython(backfill_recording_domains, reverse),
    ]
