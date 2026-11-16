import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1435_ema_issuer_management")]

    operations = [
        migrations.CreateModel(
            name="TeamEventsTableConfig",
            fields=[
                (
                    "team",
                    models.OneToOneField(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="posthog.team",
                    ),
                ),
                (
                    "use_new_events_table",
                    models.BooleanField(blank=True, null=True),
                ),
            ],
        ),
    ]
