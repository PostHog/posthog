import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models.insight import Insight
from posthog.models.subscription import Subscription, SubscriptionDelivery
from posthog.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from posthog.temporal.subscriptions.types import SnapshotInsightsInputs

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def _run(inputs: SnapshotInsightsInputs):
    env = ActivityEnvironment()
    return await env.run(snapshot_subscription_insights, inputs)


@sync_to_async
def _set_ai_consent(subscription: Subscription, approved: bool) -> None:
    subscription.team.organization.is_ai_data_processing_approved = approved
    subscription.team.organization.save()


@sync_to_async
def _create_subscription(team, user, *, summary_enabled: bool = True) -> Subscription:
    insight = Insight.objects.create(team=team, name="Pageviews", created_by=user)
    return Subscription.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
        summary_enabled=summary_enabled,
    )


@sync_to_async
def _create_delivery(subscription: Subscription, content_snapshot: dict) -> SubscriptionDelivery:
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=subscription.team,
        status=SubscriptionDelivery.Status.STARTING,
        content_snapshot=content_snapshot,
    )


async def test_skips_summary_when_org_has_not_approved_ai(team, user):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=False)
    delivery = await _create_delivery(
        subscription,
        {"insights": [{"id": subscription.insight_id, "name": "Pageviews", "query_results": {"result": []}}]},
    )

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    assert result.summary_text is None


async def test_runs_summary_when_org_has_approved_ai(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    called = {}

    def fake_generate(previous_states, current_states, **kwargs):
        called["ran"] = True
        return "- Pageviews is trending up"

    monkeypatch.setattr(
        "posthog.temporal.subscriptions.snapshot_activities.generate_change_summary",
        fake_generate,
    )

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    assert called.get("ran") is True
    assert result.summary_text == "- Pageviews is trending up"


async def test_skips_summary_when_summary_not_enabled(team, user):
    subscription = await _create_subscription(team, user, summary_enabled=False)
    await _set_ai_consent(subscription, approved=True)

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(uuid.uuid4()),
        )
    )

    assert result.summary_text is None
