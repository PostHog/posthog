import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.temporal.sync_events_retention.activities import sync_events_retention
from posthog.temporal.sync_events_retention.types import SyncEventsRetentionInput

# These run against the real DB on purpose: the activity's value is in its real queryset
# (select_related/.only), reading a real Organization.available_product_features via
# get_available_feature, and persisting via bulk_update. Mocking Team.objects would hide
# exactly those — which is how a select_related/.only() FieldError shipped undetected.


async def _team_with_features(features: list[dict], *, current_months: int) -> Team:
    org = await sync_to_async(Organization.objects.create)(name="test-org")
    team = await sync_to_async(Team.objects.create)(
        organization=org, name="test-team", event_retention_months=current_months
    )
    # available_product_features is recomputed from licenses by a pre_save signal on create, so set it with a
    # direct UPDATE (which bypasses save/signals) — this mirrors how billing actually populates the field.
    await sync_to_async(Organization.objects.filter(pk=org.pk).update)(available_product_features=features)
    return team


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "features, expected_months",
    [
        # Real entitlement under the key billing actually emits -> converted to months and written.
        # Also guards the billing key: a wrong key would miss this feature and grandfather to 84 instead.
        ([{"key": "product_analytics_data_retention", "limit": 1, "unit": "year"}], 12),
        # A present-but-unrelated feature must be ignored -> grandfather to 7 years (84 months).
        ([{"key": "some_other_feature", "limit": 1, "unit": "year"}], 84),
    ],
)
async def test_syncs_event_retention_months_from_billing(features: list[dict], expected_months: int):
    # Start at a sentinel that differs from every expected value, so the assertion proves a real write.
    team = await _team_with_features(features, current_months=999)

    await ActivityEnvironment().run(sync_events_retention, SyncEventsRetentionInput(dry_run=False))

    await sync_to_async(team.refresh_from_db)()
    assert team.event_retention_months == expected_months


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_dry_run_computes_but_does_not_persist():
    team = await _team_with_features(
        [{"key": "product_analytics_data_retention", "limit": 1, "unit": "year"}], current_months=84
    )

    await ActivityEnvironment().run(sync_events_retention, SyncEventsRetentionInput(dry_run=True))

    await sync_to_async(team.refresh_from_db)()
    # The target is 12, but a dry run must not write it.
    assert team.event_retention_months == 84
