from time import sleep
from typing import List, Tuple

import structlog
from celery import group

from posthog.models.dashboard_tile import get_tiles_ordered_by_position
from posthog.models.exported_asset import ExportedAsset
from posthog.models.insight import Insight
from posthog.models.subscription import Subscription
from posthog.tasks.exporter import export_task

logger = structlog.get_logger(__name__)

UTM_TAGS_BASE = "utm_source=posthog&utm_campaign=subscription_report"

DEFAULT_MAX_ASSET_COUNT = 6


def generate_assets(
    subscription: Subscription, max_asset_count: int = DEFAULT_MAX_ASSET_COUNT
) -> Tuple[List[Insight], List[ExportedAsset]]:
    insights = []

    if subscription.dashboard:
        tiles = get_tiles_ordered_by_position(subscription.dashboard)
        insights = [tile.insight for tile in tiles]
    elif subscription.insight:
        insights = [subscription.insight]
    else:
        raise Exception("There are no insights to be sent for this Subscription")

    # Create all the assets we need
    assets = [
        ExportedAsset(team=subscription.team, export_format="image/png", insight=insight)
        for insight in insights[:max_asset_count]
    ]
    ExportedAsset.objects.bulk_create(assets)

    # Wait for all assets to be exported
    tasks = [export_task.s(asset.id) for asset in assets]
    parallel_job = group(tasks).apply_async()

    max_wait = 30
    while not parallel_job.ready():
        max_wait = max_wait - 1
        sleep(1)
        if max_wait < 0:
            raise Exception("Timed out waiting for exports")

    return insights, assets
