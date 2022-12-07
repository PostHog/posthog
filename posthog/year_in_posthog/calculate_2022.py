from typing import Dict, Optional

import structlog
from django.db import connection

from posthog.logging.timing import timed

logger = structlog.get_logger(__name__)

query = """
with insight_stats AS (
    SELECT
        user_id,
        insight_created_count,
        CASE
            WHEN insight_created_count >= 10 THEN 'Deep diver'
        END AS badge,
        PERCENT_RANK() OVER (
            ORDER BY
                insight_created_count
        ) AS insight_rank
    FROM
        (
            SELECT
                created_by_id AS user_id,
                count(*) AS insight_created_count
            FROM
                posthog_dashboarditem
            WHERE
                NOT created_by_id IS NULL
                AND date_part('year', created_at) = 2022
                AND (
                    name IS NOT NULL
                    OR derived_name IS NOT NULL
                )
            GROUP BY
                created_by_id
        ) AS insight_stats_inner
),
flag_stats AS (
    SELECT
        user_id,
        flag_created_count,
        CASE
            WHEN flag_created_count >= 10 THEN 'Flag raiser'
        END AS badge,
        PERCENT_RANK() OVER (
            ORDER BY
                flag_created_count
        ) AS flag_rank
    FROM
        (
            SELECT
                created_by_id AS user_id,
                count(*) AS flag_created_count
            FROM
                posthog_featureflag
            WHERE
                date_part('year', created_at) = 2022
            GROUP BY
                user_id
        ) AS flag_stats_inner
),
recording_viewed_stats AS (
    SELECT
        user_id,
        viewed_recording_count,
        CASE
            WHEN viewed_recording_count >= 10 THEN 'Popcorn muncher'
        END AS badge,
        PERCENT_RANK() OVER (
            ORDER BY
                viewed_recording_count
        ) AS viewed_recording_rank
    FROM
        (
            SELECT
                user_id,
                count(*) AS viewed_recording_count
            FROM
                posthog_sessionrecordingviewed
            WHERE
                date_part('year', created_at) = 2022
            GROUP BY
                user_id
        ) AS recording_stats_inner
),
experiments_stats AS (
    SELECT
        user_id,
        experiments_created_count,
        CASE
            WHEN experiments_created_count >= 4 THEN 'Scientist'
        END AS badge,
        PERCENT_RANK() OVER (
            ORDER BY
                experiments_created_count
        ) AS experiments_created_rank
    FROM
        (
            SELECT
                created_by_id AS user_id,
                count(*) AS experiments_created_count
            FROM
                posthog_experiment
            WHERE
                date_part('year', created_at) = 2022
            GROUP BY
                user_id
        ) AS experiment_stats_inner
),
dashboards_created_stats AS (
    SELECT
        user_id,
        dashboards_created_count,
        CASE
            WHEN dashboards_created_count >= 10 THEN 'Curator'
        END AS badge,
        PERCENT_RANK() OVER (
            ORDER BY
                dashboards_created_count
        ) AS dashboards_created_rank
    FROM
        (
            SELECT
                created_by_id AS user_id,
                count(*) AS dashboards_created_count
            FROM
                posthog_dashboard
            WHERE
                date_part('year', created_at) = 2022
                AND created_by_id is not null
            GROUP BY
                user_id
        ) AS dashboard_stats_inner
)
SELECT
    id,
    array_remove(ARRAY [case when posthog_user.last_login >= '1-Jan-2022' then 'Hedgehog' end, insight_stats.badge, flag_stats.badge, recording_viewed_stats.badge, experiments_stats.badge, dashboards_created_stats.badge], NULL) AS badges,
    insight_stats.insight_created_count, insight_stats.insight_rank,
    flag_stats.flag_created_count, flag_stats.flag_rank,
    recording_viewed_stats.viewed_recording_count, recording_viewed_stats.viewed_recording_rank,
    experiments_stats.experiments_created_count, experiments_stats.experiments_created_rank,
    dashboards_created_stats.dashboards_created_count,dashboards_created_stats.dashboards_created_rank
FROM
    posthog_user
    LEFT JOIN insight_stats ON posthog_user.id = insight_stats.user_id
    LEFT JOIN flag_stats ON posthog_user.id = flag_stats.user_id
    LEFT JOIN recording_viewed_stats ON posthog_user.id = recording_viewed_stats.user_id
    LEFT JOIN experiments_stats ON posthog_user.id = experiments_stats.user_id
    LEFT JOIN dashboards_created_stats ON posthog_user.id = dashboards_created_stats.user_id
WHERE posthog_user.id = %s
"""


def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@timed("year_in_posthog_2022")
def calculate_year_in_posthog_2022(user_id: int) -> Optional[Dict]:
    with connection.cursor() as cursor:
        cursor.execute(query, [user_id])
        results = dictfetchall(cursor)

    # we should only match one or zero users
    if results:
        result = results[0]
        return {
            "stats": {
                "insight_created_count": result["insight_created_count"],
                "insight_rank": result["insight_rank"],
                "flag_created_count": result["flag_created_count"],
                "flag_rank": result["flag_rank"],
                "viewed_recording_count": result["viewed_recording_count"],
                "viewed_recording_rank": result["viewed_recording_rank"],
                "experiments_created_count": result["experiments_created_count"],
                "experiments_created_rank": result["experiments_created_rank"],
                "dashboards_created_count": result["dashboards_created_count"],
                "dashboards_created_rank": result["dashboards_created_rank"],
            },
            "badges": result["badges"],
        }

    return None
