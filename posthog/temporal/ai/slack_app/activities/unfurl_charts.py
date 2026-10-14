from temporalio import activity

from posthog.temporal.ai.slack_app.types import (
    SlackAppUnfurlChartsPostInput,
    SlackAppUnfurlChartsPrepared,
    SlackAppUnfurlChartsWorkflowInputs,
)
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.logic.link_unfurl_charts import post_unfurl_charts, prepare_unfurl_charts


@activity.defn
@close_db_connections
def prepare_slack_unfurl_charts_activity(inputs: SlackAppUnfurlChartsWorkflowInputs) -> SlackAppUnfurlChartsPrepared:
    return prepare_unfurl_charts(inputs)


@activity.defn
@close_db_connections
def post_slack_unfurl_charts_activity(post: SlackAppUnfurlChartsPostInput) -> None:
    post_unfurl_charts(post)
