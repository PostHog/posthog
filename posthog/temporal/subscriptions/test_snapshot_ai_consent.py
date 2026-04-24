import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import structlog
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


class _FakePhClient:
    """In-memory stand-in for the real PostHog client used by `ph_scoped_capture`.

    Collects every `capture(...)` kwargs dict into `self.captured` so tests can
    assert on events without hitting the network. `shutdown` is a no-op so the
    `with ph_scoped_capture()` context manager exits cleanly.
    """

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def capture(self, **kwargs) -> None:
        self.captured.append(kwargs)

    def shutdown(self) -> None:
        pass


def _install_fake_ph_client(monkeypatch) -> _FakePhClient:
    """Mock the two seams (`is_cloud` + `get_client`) that gate `ph_scoped_capture`."""
    client = _FakePhClient()
    monkeypatch.setattr("posthog.ph_client.is_cloud", lambda: True)
    monkeypatch.setattr("posthog.ph_client.get_client", lambda *a, **kw: client)
    return client


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


async def test_captures_analytics_event_when_summary_is_generated(team, user, monkeypatch):
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

    monkeypatch.setattr(
        "posthog.temporal.subscriptions.snapshot_activities.generate_change_summary",
        lambda *a, **kw: "- Pageviews is trending up",
    )

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert len(events) == 1, f"expected one capture, got {fake_client.captured}"
    event = events[0]
    assert event["distinct_id"] == str(user.distinct_id)
    props = event["properties"]
    assert props["subscription_id"] == subscription.id
    assert props["team_id"] == subscription.team_id
    assert props["delivery_id"] == str(delivery.id)
    assert props["target_type"] == subscription.target_type
    assert props["insight_count"] == 1
    assert props["image_count"] == 0
    assert props["has_previous_snapshot"] is False
    assert props["summary_text_length"] == len("- Pageviews is trending up")
    assert props["resource_type"] == "insight"


async def test_does_not_capture_analytics_event_when_summary_skipped(team, user, monkeypatch):
    subscription = await _create_subscription(team, user, summary_enabled=False)
    await _set_ai_consent(subscription, approved=True)

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(uuid.uuid4()),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert events == []


async def test_does_not_capture_analytics_event_for_empty_summary(team, user, monkeypatch):
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

    monkeypatch.setattr(
        "posthog.temporal.subscriptions.snapshot_activities.generate_change_summary",
        lambda *a, **kw: "",
    )

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert events == [], "empty-string summaries should not count as generated"


async def test_captures_event_with_team_prefixed_distinct_id_when_no_creator(team, user, monkeypatch):
    """System-generated subs without a creator get a `team_<id>` distinct_id so they don't
    pollute real-user counts in product analytics.
    """
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    # Remove the creator link after creation so we hit the fallback branch.
    await sync_to_async(Subscription.objects.filter(pk=subscription.pk).update)(created_by=None)
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

    monkeypatch.setattr(
        "posthog.temporal.subscriptions.snapshot_activities.generate_change_summary",
        lambda *a, **kw: "- Pageviews is trending up",
    )

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert len(events) == 1
    assert events[0]["distinct_id"] == f"team_{team.id}"


async def test_unhandled_exception_is_logged_and_reraised(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {"insights": [{"id": subscription.insight_id, "name": "Pageviews", "query_results": {"result": []}}]},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("boom while building states")

    monkeypatch.setattr(
        "posthog.temporal.subscriptions.snapshot_activities._build_states_from_content_snapshot",
        boom,
    )

    with structlog.testing.capture_logs() as captured_logs:
        with pytest.raises(RuntimeError, match="boom while building states"):
            await _run(
                SnapshotInsightsInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    delivery_id=str(delivery.id),
                )
            )

    failed_events = [log for log in captured_logs if log.get("event") == "snapshot_subscription_insights.failed"]
    assert len(failed_events) == 1, f"expected one .failed log, got {failed_events}"
    assert failed_events[0]["subscription_id"] == subscription.id
    assert failed_events[0]["delivery_id"] == str(delivery.id)
    assert failed_events[0]["log_level"] == "error"
