from datetime import timedelta
from typing import Dict, Optional

from django.conf import settings
from django.db import connection

from posthog.cache_utils import cache_for

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
        AND date_part('year', created_at) = 2023
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
            WHEN count(*) >= 5 THEN 'flag_raiser'
        END AS badge
    FROM
        posthog_featureflag
    WHERE
        -- only having a single percentage symbol here gives very misleading Python errors :/
        key not ilike 'survey-targeting%%'
        AND key not ilike 'prompt-%%'
        AND key not ilike 'interview-%%'
        AND date_part('year', created_at) = 2023
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        created_by_id
),
recording_viewed_stats AS (
    SELECT
        user_id,
        count(*) AS viewed_recording_count,
        CASE
            WHEN count(*) >= 59 THEN 'popcorn_muncher'
        END AS badge
    FROM
        posthog_sessionrecordingviewed
    WHERE
        date_part('year', created_at) = 2023
        AND user_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        user_id
),
experiments_stats AS (
    SELECT
        created_by_id AS user_id,
        count(*) AS experiments_created_count,
        CASE
            WHEN count(*) >= 3 THEN 'scientist'
        END AS badge
    FROM
        posthog_experiment
    WHERE
        date_part('year', created_at) = 2023
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        created_by_id
),
dashboards_created_stats AS (
    SELECT
        created_by_id AS user_id,
        count(*) AS dashboards_created_count,
        CASE
            WHEN count(*) >= 4 THEN 'curator'
        END AS badge
    FROM
        posthog_dashboard
    WHERE
        date_part('year', created_at) = 2023
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    GROUP BY
        created_by_id
),
survey_stats AS (
    SELECT
        created_by_id as user_id,
        count(*) as survey_created_count,
        CASE
            WHEN count(*) >= 1 THEN 'reporter'
        END AS badge
    FROM
        posthog_survey
    WHERE
        NOT created_by_id IS NULL
        AND date_part('year', created_at) = 2023
        AND created_by_id = (select id from posthog_user where uuid = %(user_uuid)s)
    group by
        created_by_id
)
SELECT
    id,
    array_remove(
        ARRAY [
        case when posthog_user.last_login >= '1-Jan-2023' then 'astronaut' end,
        insight_stats.badge,
        flag_stats.badge,
        recording_viewed_stats.badge,
        experiments_stats.badge,
        dashboards_created_stats.badge,
        survey_stats.badge
    ],
        NULL
    ) AS badges,
    insight_stats.insight_created_count,
    flag_stats.flag_created_count,
    recording_viewed_stats.viewed_recording_count,
    experiments_stats.experiments_created_count,
    dashboards_created_stats.dashboards_created_count,
    survey_stats.survey_created_count
FROM
    posthog_user
    LEFT JOIN insight_stats ON posthog_user.id = insight_stats.user_id
    LEFT JOIN flag_stats ON posthog_user.id = flag_stats.user_id
    LEFT JOIN recording_viewed_stats ON posthog_user.id = recording_viewed_stats.user_id
    LEFT JOIN experiments_stats ON posthog_user.id = experiments_stats.user_id
    LEFT JOIN dashboards_created_stats ON posthog_user.id = dashboards_created_stats.user_id
    LEFT JOIN survey_stats ON posthog_user.id = survey_stats.user_id
WHERE
    posthog_user.uuid = %(user_uuid)s
"""


def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@cache_for(timedelta(seconds=0 if settings.DEBUG else 30))
def calculate_year_in_posthog_2023(user_uuid: str) -> Optional[Dict]:
    with connection.cursor() as cursor:
        cursor.execute(query, {"user_uuid": user_uuid})
        rows = dictfetchall(cursor)

    # we should only match one or zero users
    if rows:
        row = rows[0]
        badges_ = row["badges"]
        if len(badges_) >= 3:
            badges_.append("champion")

        return {
            "stats": {
                "insight_created_count": row["insight_created_count"],
                "flag_created_count": row["flag_created_count"],
                "viewed_recording_count": row["viewed_recording_count"],
                "experiments_created_count": row["experiments_created_count"],
                "dashboards_created_count": row["dashboards_created_count"],
                "surveys_created_count": row["survey_created_count"],
            },
            "badges": badges_,
        }

    return None
