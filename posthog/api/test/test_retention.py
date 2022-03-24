import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.test import Client

from posthog.api.test.test_event_definition import EventData, capture_event


def identify(
    distinct_id: str,
    team_id: int,
    # TODO: I believe the handling of properties here isn't totally true to how
    # it is handled in reality. We could update for `identify` to reflect
    # reality, but I think really we should update to use the `/e/` endpoint and
    # remove any room for discrepancies.
    properties: Optional[Dict[str, Any]] = None,
):
    """
    Simulate what is being done in the plugin-server, so we end up with the
    database in the right state
    """
    properties = properties or {}

    from ee.clickhouse.models.person import Person, PersonDistinctId

    person = Person.objects.create(team_id=team_id, properties=properties)
    PersonDistinctId.objects.create(distinct_id=distinct_id, team_id=team_id, person_id=person.id)

    capture_event(
        event=EventData(
            event="$identify",
            team_id=team_id,
            distinct_id=distinct_id,
            timestamp=datetime.now(),
            properties={"distinct_id": distinct_id},
        )
    )


def get_retention(
    client: Client,
    display: str,
    events: List[Dict[str, Any]],
    date_from: str,
    date_to: str,
    selected_interval: int,
    total_intervals: int,
    target_entity: Dict[str, Any],
    returning_entity: Dict[str, Any],
    insight: str,
    period: str,
    retention_type: str,
    properties: Optional[List[Dict[str, Any]]] = None,
    filter_test_accounts: bool = True,
):
    return client.get(
        "/api/person/retention",
        data={
            "display": display,
            "events": json.dumps(events),
            "date_from": date_from,
            "date_to": date_to,
            "selected_interval": selected_interval,
            "total_intervals": total_intervals,
            "filter_test_accounts": filter_test_accounts,
            "insight": insight,
            "period": period,
            "retention_type": retention_type,
            "target_entity": json.dumps(target_entity),
            "returning_entity": json.dumps(returning_entity),
            "properties": json.dumps(properties or []),
        },
    )
