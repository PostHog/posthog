from datetime import datetime
from typing import Dict, List, Union

from ee.clickhouse.models.element import create_elements
from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.person import check_and_create_person_distinct_ids
from posthog.models.team import Team


# TODO: timestamp QA (make sure these are consistent)
# TODO: handle siteurl for action trigger
def capture_ee(
    event: str,
    distinct_id: str,
    properties: Dict,
    site_url: str,
    team: Team,
    timestamp: Union[datetime, str],
    elements: List,
) -> None:
    # determine/create elements
    element_hash = create_elements(elements, team)

    # # determine create events
    create_event(
        event=event,
        properties=properties,
        timestamp=timestamp,
        team=team,
        element_hash=element_hash,
        distinct_id=distinct_id,
    )

    # # check/create persondistinctid
    check_and_create_person_distinct_ids(ids=[distinct_id], team=team)
