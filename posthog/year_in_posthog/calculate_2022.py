from datetime import timedelta
from typing import Dict, Optional

from django.db import connection

from posthog.cache_utils import cache_for
from posthog.logging.timing import timed

query = """
with insight_stats AS (
    SELECT
        created_by_id as user_id,
        count(*) as insight_created_count,
        CASE
            WHEN count(*) >= 10 THEN 'deep_diver'
        END AS badge
    FROM
        posthog_dashboarditem
    WHERE
        NOT created_by_id IS NULL
        AND date_part('year', created_at) = 2022
        AND (
            name IS NOT NULL
            OR derived_name IS NOT NULL
        )
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    group by
        created_by_id
),
flag_stats AS (
    SELECT
        created_by_id AS user_id,
        count(*) AS flag_created_count,
        CASE
            WHEN count(*) >= 10 THEN 'flag_raiser'
        END AS badge
    FROM
        posthog_featureflag
    WHERE
        date_part('year', created_at) = 2022
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        created_by_id
),
recording_viewed_stats AS (
    SELECT
        user_id,
        count(*) AS viewed_recording_count,
        CASE
            WHEN count(*) >= 50 THEN 'popcorn_muncher'
        END AS badge
    FROM
        posthog_sessionrecordingviewed
    WHERE
        date_part('year', created_at) = 2022
        AND user_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        user_id
),
experiments_stats AS (
    SELECT
        created_by_id AS user_id,
        count(*) AS experiments_created_count,
        CASE
            WHEN count(*) >= 4 THEN 'scientist'
        END AS badge
    FROM
        posthog_experiment
    WHERE
        date_part('year', created_at) = 2022
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        created_by_id
),
dashboards_created_stats AS (
    SELECT
        created_by_id AS user_id,
        count(*) AS dashboards_created_count,
        CASE
            WHEN count(*) >= 10 THEN 'curator'
        END AS badge
    FROM
        posthog_dashboard
    WHERE
        date_part('year', created_at) = 2022
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        created_by_id
)
SELECT
    id,
    array_remove(
        ARRAY [
        case when posthog_user.last_login >= '1-Jan-2022' then 'astronaut' end,
        insight_stats.badge,
        flag_stats.badge,
        recording_viewed_stats.badge,
        experiments_stats.badge,
        dashboards_created_stats.badge,
        case when
            recording_viewed_stats.badge is not null
                and flag_stats.badge is not null
                and insight_stats.badge is not null
            then 'champion' end
    ],
        NULL
    ) AS badges,
    insight_stats.insight_created_count,
    flag_stats.flag_created_count,
    recording_viewed_stats.viewed_recording_count,
    experiments_stats.experiments_created_count,
    dashboards_created_stats.dashboards_created_count
FROM
    posthog_user
    LEFT JOIN insight_stats ON posthog_user.id = insight_stats.user_id
    LEFT JOIN flag_stats ON posthog_user.id = flag_stats.user_id
    LEFT JOIN recording_viewed_stats ON posthog_user.id = recording_viewed_stats.user_id
    LEFT JOIN experiments_stats ON posthog_user.id = experiments_stats.user_id
    LEFT JOIN dashboards_created_stats ON posthog_user.id = dashboards_created_stats.user_id
WHERE
    posthog_user.uuid = %(user_uuid)s
"""


def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@timed("year_in_posthog_2022_calculation")
@cache_for(timedelta(seconds=30))
def calculate_year_in_posthog_2022(user_uuid: str) -> Optional[Dict]:
    with connection.cursor() as cursor:
        cursor.execute(query, {"user_uuid": user_uuid})
        rows = dictfetchall(cursor)

    # we should only match one or zero users
    if rows:
        row = rows[0]
        return {
            "stats": {
                "insight_created_count": row["insight_created_count"],
                "flag_created_count": row["flag_created_count"],
                "viewed_recording_count": row["viewed_recording_count"],
                "experiments_created_count": row["experiments_created_count"],
                "dashboards_created_count": row["dashboards_created_count"],
            },
            "badges": row["badges"],
        }

    return None
