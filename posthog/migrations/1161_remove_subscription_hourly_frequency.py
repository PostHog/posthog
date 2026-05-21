from django.db import migrations


def soft_delete_hourly_subscriptions(apps, schema_editor):
    Subscription = apps.get_model("posthog", "Subscription")
    Subscription.objects.filter(frequency="hourly").update(
        deleted=True,
        enabled=False,
        next_delivery_date=None,
        frequency="daily",
    )


class Migration(migrations.Migration):
    dependencies = [("posthog", "1160_materializedcolumnslot_run_id_concurrent_idx")]

    operations = [
        migrations.RunPython(
            soft_delete_hourly_subscriptions,
            reverse_code=migrations.RunPython.noop,
            elidable=True,
        ),
    ]
