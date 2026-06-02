from django.conf import settings
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0023_migrate_data_modeling_models"),
        ("posthog", "1193_oauthaccesstoken_label_oauthapplication_scopes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["team", "status"], name="datamodelingjob_team_status"),
        ),
    ]
