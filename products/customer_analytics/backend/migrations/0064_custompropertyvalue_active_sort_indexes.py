import django.db.models.functions.text
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("customer_analytics", "0063_teamcustomeranalyticsconfig_properties"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="custompropertyvalue",
            index=models.Index(
                models.F("team"),
                models.F("definition"),
                django.db.models.functions.text.Left("value_str", 256),
                models.F("account"),
                condition=models.Q(("is_deleted", False), ("value_str__isnull", False)),
                name="cpv_active_sort_str_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="custompropertyvalue",
            index=models.Index(
                models.F("team"),
                models.F("definition"),
                models.F("value_bool"),
                models.F("account"),
                condition=models.Q(("is_deleted", False), ("value_bool__isnull", False)),
                name="cpv_active_sort_bool_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="custompropertyvalue",
            index=models.Index(
                models.F("team"),
                models.F("definition"),
                models.F("value_num"),
                models.F("account"),
                condition=models.Q(("is_deleted", False), ("value_num__isnull", False)),
                name="cpv_active_sort_num_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="custompropertyvalue",
            index=models.Index(
                models.F("team"),
                models.F("definition"),
                models.F("value_datetime"),
                models.F("account"),
                condition=models.Q(("is_deleted", False), ("value_datetime__isnull", False)),
                name="cpv_active_sort_datetime_idx",
            ),
        ),
    ]
