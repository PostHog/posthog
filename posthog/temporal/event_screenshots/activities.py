from uuid import uuid4

from django.db import connection

from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client as get_ch_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.event_screenshots.types import (
    ClickHouseResponse,
    EventSession,
    EventType,
    LoadEventSessionsResult,
)

LOGGER = get_write_only_logger()


EVENT_TYPE_QUERY = """
SELECT
	ed.name,
	ed.team_id
FROM posthog_eventdefinition ed
INNER JOIN posthog_eventproperty ep
ON
	ed.name = ep.event
	AND ed.team_id = ep.team_id
WHERE
	ed.last_seen_at > now() - INTERVAL '3' HOUR
	AND ed.name NOT LIKE '$%'
	AND ep.property = '$current_url'
"""


@database_sync_to_async
def _query_event_types():
    with connection.cursor() as cur:
        cur.execute(EVENT_TYPE_QUERY)
        results = cur.fetchall()
    return [
        EventType(
            name=row[0],
            team_id=row[1],
        )
        for row in results
    ]


@activity.defn(name="load-event-types")
async def load_event_types() -> list[EventType]:
    logger = LOGGER.bind()
    logger.info(f"Loading event types")
    return await _query_event_types()


SESSION_QUERY = """
WITH matching_events AS (
	SELECT
		timestamp as ts,
		mat_$current_url as url,
		$session_id as session_id,
		team_id
	FROM
		events
	PREWHERE
		event = %(event_name)s
		AND team_id = %(team_id)s
		AND timestamp > now() - INTERVAL 3 HOUR
		AND mat_$lib = 'web'
),
matching_sessions AS (
    SELECT
        session_id,
        min(min_first_timestamp) as start
    FROM session_replay_events
    PREWHERE
        min_first_timestamp > now() - interval 1 day
        AND team_id = %(team_id)s
    GROUP BY session_id
)
SELECT
	session_id,
	dateDiff('second', start, ts) AS timestamp,
	url
FROM matching_sessions AS se
JOIN matching_events AS me
ON
    se.session_id = me.session_id
FORMAT JSON
"""


@activity.defn(name="load-event-sessions")
async def load_event_sessions(event_types: list[EventType]) -> LoadEventSessionsResult:
    logger = LOGGER.bind()
    logger.info(f"Loading event sessions")

    async with get_ch_client() as ch_client:
        result = []
        for event_type in event_types:
            parameters = {
                "team_id": event_type.team_id,
                "event_name": event_type.name,
            }

            raw_response: bytes = b""
            async with ch_client.aget_query(
                query=SESSION_QUERY,
                query_parameters=parameters,
                query_id=str(uuid4()),
            ) as ch_response:
                raw_response = await ch_response.content.read()

            response = ClickHouseResponse.model_validate_json(raw_response)
            if response.data:
                event_session = EventSession.model_validate(response.data[0])
                result.append((event_type, event_session))

    return LoadEventSessionsResult(
        event_sessions=result,
    )
