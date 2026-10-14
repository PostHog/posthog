from datetime import UTC, datetime, timedelta

from temporalio import activity

from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
    SlackUnfurlChartAsset,
)
from posthog.temporal.common.utils import close_db_connections

from products.exports.backend.facade.api import (
    create_insight_png_export,
    get_delivery_image_url,
    png_export_has_content,
)
from products.slack_app.backend.logic.link_unfurl_charts import post_unfurl_charts, unfurl_chart_targets

# The export calls live here and not in the Slack app, because the exports product already
# depends on the Slack app and the Slack app must not depend back on it.

# Slack fetches image_url again after the unfurl is posted, so the token must outlive the post.
_CHART_URL_TTL = timedelta(days=30)
_CHART_ASSET_TTL = timedelta(days=31)


@activity.defn
@close_db_connections
def prepare_slack_unfurl_charts_activity(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    targets = unfurl_chart_targets(inputs)
    assets: list[SlackUnfurlChartAsset] = []
    for insight_id in targets.insight_ids:
        try:
            asset_id = create_insight_png_export(
                team=targets.team,
                created_by=targets.user,
                insight_id=insight_id,
                is_system=True,
                expires_after=datetime.now(UTC) + _CHART_ASSET_TTL,
            )
        except ValueError:
            continue
        assets.append(SlackUnfurlChartAsset(insight_id=insight_id, asset_id=asset_id))
    return SlackAppUnfurlChartsPrepared(distinct_id=str(targets.user.distinct_id), assets=assets)


@activity.defn
@close_db_connections
def post_slack_unfurl_charts_activity(post: SlackAppUnfurlChartsPostInput) -> None:
    request = post.request
    image_urls_by_insight: dict[int, str] = {}
    for asset in post.rendered:
        if not png_export_has_content(team_id=request.team_id, asset_id=asset.asset_id):
            continue
        # created_by_id ties the asset to the sharer who rendered it.
        image_url = get_delivery_image_url(
            team_id=request.team_id,
            asset_id=asset.asset_id,
            expiry_delta=_CHART_URL_TTL,
            created_by_id=request.user_id,
        )
        if image_url is not None:
            image_urls_by_insight[asset.insight_id] = image_url
    post_unfurl_charts(post, image_urls_by_insight=image_urls_by_insight)
