from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1133_alter_integration_kind"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="insightviewed",
            index=models.Index(
                fields=["insight_id", "-last_viewed_at"],
                name="insightviewed_insight_lva_idx",
            ),
        ),
    ]
