import django.db.models.deletion
from django.db import migrations, models


def backfill_subscription_integration(apps, schema_editor):
    """
    Pin existing Slack subscriptions to the same integration that
    get_slack_integration_for_team would return (lowest id, matching
    the .first() default ordering). This prevents silent integration
    switches when a team later adds a second Slack integration.
    """
    Subscription = apps.get_model("posthog", "Subscription")
    Integration = apps.get_model("posthog", "Integration")

    slack_subs = list(
        Subscription.objects.filter(
            target_type="slack",
            integration__isnull=True,
            deleted=False,
        ).values_list("id", "team_id")
    )

    # Build lookup: team_id -> first slack integration id (by lowest id)
    team_ids = {team_id for _, team_id in slack_subs}
    team_to_integration: dict[int, int] = {}
    for integration in (
        Integration.objects.filter(team_id__in=team_ids, kind="slack").order_by("id").only("id", "team_id")
    ):
        if integration.team_id not in team_to_integration:
            team_to_integration[integration.team_id] = integration.id

    # Batch update per integration
    integration_to_sub_ids: dict[int, list[int]] = {}
    for sub_id, team_id in slack_subs:
        integration_id = team_to_integration.get(team_id)
        if integration_id:
            integration_to_sub_ids.setdefault(integration_id, []).append(sub_id)

    for integration_id, sub_ids in integration_to_sub_ids.items():
        Subscription.objects.filter(id__in=sub_ids).update(integration_id=integration_id)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1039_subscription_dashboard_export_insights"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="integration",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="posthog.integration",
            ),
        ),
        migrations.RunPython(backfill_subscription_integration, migrations.RunPython.noop),
    ]
