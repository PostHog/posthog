from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1156_subscription_ai_fields"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="subscription",
            index=models.Index(fields=["content_type"], name="posthog_sub_content_type_idx"),
        ),
    ]
