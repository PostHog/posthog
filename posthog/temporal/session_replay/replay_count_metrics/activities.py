from prometheus_client import Gauge
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.metrics import pushed_metrics_registry
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.session_replay.replay_count_metrics.types import ReplayCountMetricsInput

LOGGER = get_write_only_logger()

METRICS = [
    "all_recordings",
    "mobile_recordings",
    "web_recordings",
    "invalid_web_recordings",
]
DESCRIPTIONS = [
    "All recordings that started in the last hour",
    "Recordings started in the last hour that are from mobile",
    "Recordings started in the last hour that are from web",
    "Acts as a proxy for replay sessions which haven't received a full snapshot",
]

QUERY = """
select
    count() as all_recordings,
    countIf(snapshot_source == 'mobile') as mobile_recordings,
    countIf(snapshot_source == 'web') as web_recordings,
    countIf(snapshot_source =='web' and first_url is null) as invalid_web_recordings
from (
    select any(team_id) as team_id, argMinMerge(first_url) as first_url, argMinMerge(snapshot_source) as snapshot_source
    from session_replay_events
    where min_first_timestamp >= now() - interval 65 minute
    and min_first_timestamp <= now() - interval 5 minute
    group by session_id
)
FORMAT JSONEachRow
"""


@activity.defn(name="collect-replay-count-metrics")
async def collect_replay_count_metrics(input: ReplayCountMetricsInput) -> None:
    logger = LOGGER.bind(activity="collect-replay-count-metrics")
    logger.info("Collecting replay count metrics")

    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, name="replay_count_metrics")

    async with get_client() as client:
        rows = await client.read_query_as_jsonl(QUERY)

    if not rows:
        raise RuntimeError("ClickHouse returned empty result for replay count metrics")

    row = rows[0]

    with pushed_metrics_registry("temporal_replay_tracking") as registry:
        for metric_name, description in zip(METRICS, DESCRIPTIONS):
            gauge = Gauge(
                f"replay_tracking_{metric_name}",
                description,
                registry=registry,
            )
            gauge.set(row[metric_name])

    logger.info(
        "Replay count metrics collected",
        all=row["all_recordings"],
        mobile=row["mobile_recordings"],
        web=row["web_recordings"],
        invalid=row["invalid_web_recordings"],
    )
