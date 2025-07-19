import dagster

from . import resources
from dags import web_preaggregated_s3

defs = dagster.Definitions(
    assets=[
        web_preaggregated_s3.web_stats_daily_s3,
        web_preaggregated_s3.web_bounces_daily_s3,
    ],
    jobs=[
        web_preaggregated_s3.web_analytics_s3_job,
    ],
    resources=resources,
)
