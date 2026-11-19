from datetime import datetime, timedelta

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .queries import MAX_EXECUTION_TIME_SECONDS

# Cross-team by design: one aggregate over the visited teams instead of one query per team.
_GENERATION_DAYS_SQL = """
SELECT
    team_id,
    uniqExact(toDate(timestamp)) AS days_28,
    uniqExactIf(toDate(timestamp), timestamp >= %(week_start)s) AS days_7
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$ai_generation'
  AND timestamp >= %(start)s
  AND timestamp < %(end)s
GROUP BY team_id
"""


@frozen
class GenerationDaysRow:
    team_id: int
    # Days with generations in the 28 and the 7 days before now.
    days_28: int
    days_7: int


def load_generation_days(team_ids: list[int], now: datetime) -> list[GenerationDaysRow]:
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.EVAL_SUGGESTIONS):
        rows = sync_execute(
            _GENERATION_DAYS_SQL,
            {
                "team_ids": team_ids,
                "start": now - timedelta(days=28),
                "week_start": now - timedelta(days=7),
                "end": now,
            },
            workload=Workload.OFFLINE,
            # Well inside the plan activity's 10 minutes, so a slow batch fails the query, not the activity.
            settings={"max_execution_time": MAX_EXECUTION_TIME_SECONDS},
        )
    return [GenerationDaysRow(team_id=int(row[0]), days_28=int(row[1]), days_7=int(row[2])) for row in rows]
