from django.db import migrations


def delete_relationless_subscriptions(apps, schema_editor):
    # A subscription with neither an insight nor a dashboard has no content to export, can
    # never deliver, and has no UI entry point (subscriptions are only reachable via their
    # insight/dashboard). Such rows slipped in via a create-time guard that never fired —
    # purge them. SubscriptionDelivery rows cascade away with them.
    Subscription = apps.get_model("posthog", "Subscription")
    Subscription.objects.filter(insight__isnull=True, dashboard__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1190_team_llm_gateway_metadata"),
    ]

    operations = [
        # Data-only, irreversible: deleted rows are unrecoverable, so the reverse is a no-op.
        migrations.RunPython(delete_relationless_subscriptions, reverse_code=migrations.RunPython.noop),
    ]
