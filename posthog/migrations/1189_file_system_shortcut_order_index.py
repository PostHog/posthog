from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models.expressions import F
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1188_migrate_cdp_models"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="filesystemshortcut",
            index=models.Index(
                F("team_id"),
                F("user_id"),
                F("order"),
                Lower("path"),
                name="posthog_fss_t_u_ordpathlc",
            ),
        ),
    ]
