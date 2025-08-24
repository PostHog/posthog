import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async

from ee.tasks.subscriptions.subscription_utils import (
    DEFAULT_MAX_ASSET_COUNT,
    generate_assets_async,
)
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest_asyncio.fixture
async def organization():
    """Create a test organization."""
    return await sync_to_async(Organization.objects.create)(name="Test Organization")


@pytest_asyncio.fixture
async def user(organization):
    """Create a test user."""
    import uuid

    unique_email = f"test-{uuid.uuid4()}@posthog.com"
    user = await sync_to_async(User.objects.create_user)(
        email=unique_email,
        password="password123",
        first_name="Test",
        last_name="User",
    )
    await sync_to_async(organization.members.add)(user)
    return user


@pytest_asyncio.fixture
async def team(organization):
    """Create a test team."""
    return await sync_to_async(Team.objects.create)(organization=organization, name="Test Team")


@pytest_asyncio.fixture
async def insight(team):
    """Create a test insight."""
    return await sync_to_async(Insight.objects.create)(team=team, short_id="123456", name="My Test subscription")


@pytest_asyncio.fixture
async def dashboard(team, user):
    """Create a test dashboard."""
    return await sync_to_async(Dashboard.objects.create)(team=team, name="private dashboard", created_by=user)


@pytest_asyncio.fixture
async def dashboard_with_tiles(team, dashboard):
    """Create a dashboard with multiple insights and tiles."""
    tiles = []
    for i in range(10):
        insight = await sync_to_async(Insight.objects.create)(
            team=team, short_id=f"insight-{i}", name=f"Test insight {i}"
        )
        tile = await sync_to_async(DashboardTile.objects.create)(dashboard=dashboard, insight=insight)
        tiles.append(tile)
    return dashboard, tiles


async def test_generate_assets_async_for_insight(team, insight, user):
    """Test generate_assets_async with a single insight subscription."""
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)

    insights, assets = await generate_assets_async(subscription)

    assert insights == [insight]
    assert len(assets) == 1
    assert assets[0].team == team
    assert assets[0].insight == insight
    assert assets[0].export_format == "image/png"

    # Verify the asset was saved to the database
    assert assets[0].id is not None
    saved_asset = await sync_to_async(ExportedAsset.objects.get)(id=assets[0].id)
    assert saved_asset.team_id == team.id
    assert saved_asset.insight_id == insight.id


async def test_generate_assets_async_for_dashboard(team, user, dashboard_with_tiles):
    """Test generate_assets_async with a dashboard subscription."""
    dashboard, tiles = dashboard_with_tiles
    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    insights, assets = await generate_assets_async(subscription)

    assert len(insights) == len(tiles)
    assert len(assets) == DEFAULT_MAX_ASSET_COUNT

    # Verify all assets were saved to the database
    for asset in assets:
        assert asset.id is not None
        assert asset.team_id == team.id
        assert asset.dashboard_id == dashboard.id
        assert asset.export_format == "image/png"

        saved_asset = await sync_to_async(ExportedAsset.objects.get)(id=asset.id)
        assert saved_asset.team_id == team.id
        assert saved_asset.dashboard_id == dashboard.id


async def test_generate_assets_async_excludes_deleted_insights(team, user, dashboard_with_tiles):
    """Test that generate_assets_async excludes deleted insights from dashboard."""
    dashboard, tiles = dashboard_with_tiles

    # Mark most insights as deleted
    for i in range(1, 10):
        tile = tiles[i]
        if tile.insight is not None:
            tile.insight.deleted = True
            await sync_to_async(tile.insight.save)()

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    insights, assets = await generate_assets_async(subscription)

    assert len(insights) == 1  # Only one non-deleted insight
    assert len(assets) == 1
    assert assets[0].insight_id == tiles[0].insight_id


async def test_generate_assets_async_raises_if_missing_resource(team, user):
    """Test that generate_assets_async raises exception for subscription with no insight or dashboard."""
    subscription = await sync_to_async(create_subscription)(team=team, created_by=user)

    with pytest.raises(Exception, match="There are no insights to be sent for this Subscription"):
        await generate_assets_async(subscription)


async def test_generate_assets_async_respects_max_asset_count(team, user, dashboard_with_tiles):
    """Test that generate_assets_async respects the max_asset_count parameter."""
    dashboard, tiles = dashboard_with_tiles
    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    max_count = 3
    insights, assets = await generate_assets_async(subscription, max_asset_count=max_count)

    assert len(insights) == len(tiles)  # All insights are returned
    assert len(assets) == max_count  # But only max_count assets are created


async def test_generate_assets_async_handles_empty_dashboard(team, user):
    """Test generate_assets_async with a dashboard that has no insights."""
    empty_dashboard = await sync_to_async(Dashboard.objects.create)(team=team, name="empty dashboard", created_by=user)

    subscription = await sync_to_async(create_subscription)(team=team, dashboard=empty_dashboard, created_by=user)

    insights, assets = await generate_assets_async(subscription)

    assert len(insights) == 0
    assert len(assets) == 0


async def test_generate_assets_async_concurrent_asset_creation(team, user, dashboard_with_tiles):
    """Test that multiple assets are created and processed concurrently."""
    dashboard, tiles = dashboard_with_tiles
    subscription = await sync_to_async(create_subscription)(team=team, dashboard=dashboard, created_by=user)

    # This test verifies that the async function completes without errors
    # when processing multiple assets concurrently
    insights, assets = await generate_assets_async(subscription)

    assert len(assets) == DEFAULT_MAX_ASSET_COUNT

    # All assets should be created in the database
    asset_ids = [asset.id for asset in assets]
    saved_assets: list[ExportedAsset] = await sync_to_async(
        lambda: list(ExportedAsset.objects.filter(id__in=asset_ids)), thread_sensitive=False
    )()
    assert len(saved_assets) == DEFAULT_MAX_ASSET_COUNT
