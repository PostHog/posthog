import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from unittest.mock import ANY

import pytest
from django.test import Client
from freezegun.api import freeze_time

from posthog.api.test.test_event_definition import (
    EventData,
    capture_event,
    create_organization,
    create_team,
    create_user,
)
from posthog.constants import TREND_FILTER_TYPE_EVENTS
from posthog.utils import is_clickhouse_enabled


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

    if is_clickhouse_enabled():
        from ee.clickhouse.models.person import Person, PersonDistinctId

        person = Person.objects.create(team_id=team_id, properties=properties)
        PersonDistinctId.objects.create(distinct_id=distinct_id, team_id=team_id, person_id=person.id)
    else:
        from posthog.models.person import Person, PersonDistinctId

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


@pytest.mark.django_db
@freeze_time("2021-08-03")
def test_insight_retention_missing_persons_gh_5443(client: Client):
    """
    This is a regression test for GH-5443.

    The scenario here is that, an api request is being made for person retention, specifically for:

      1. a "Week" period is being requested
      2. events just over a week from the first event for a user

    """

    organization = create_organization(name="test org")
    team = create_team(organization=organization)
    user = create_user("user", "pass", organization)

    identify(distinct_id="abc", team_id=team.id)

    #  This event will be the first event for the Person wrt the retention
    #  period
    capture_event(
        event=EventData(
            event="event_name", team_id=team.id, distinct_id="abc", timestamp=datetime(2021, 3, 29), properties={},
        )
    )

    # Create an event for just over a week from the initial identify event
    capture_event(
        event=EventData(
            event="event_name", team_id=team.id, distinct_id="abc", timestamp=datetime(2021, 4, 5), properties={},
        )
    )

    client.force_login(user)

    # These params are taken from
    # https://sentry.io/organizations/posthog/issues/2516393859/events/df790b8837a54051a140aa1fee51adfc/?project=1899813
    response = get_retention(
        client=client,
        events=[
            {
                "id": "$pageview",
                "math": None,
                "name": "$pageview",
                "type": "events",
                "order": 0,
                "properties": [],
                "math_property": None,
            }
        ],
        date_from="-90d",
        date_to="2021-03-31T18:22:50.579Z",
        display="ActionsTable",
        selected_interval=10,
        total_intervals=11,
        insight="RETENTION",
        period="Week",
        retention_type="retention_first_time",
        target_entity={"id": "event_name", "name": "event_name", "type": "events", "order": 0},
        returning_entity={
            "id": "event_name",
            "math": None,
            "name": "event_name",
            "type": "events",
            "order": None,
            "properties": [],
            "math_property": None,
        },
    )

    assert response.status_code == 200, response.content
    data = response.json()

    # NOTE: prior to the fix for GH-5443, this test would fail by returning an
    # empty list. To "fix" I have make the generation of "appearances" more
    # forgiving of getting too much data from the clickhouse query.
    assert data["result"] == [
        {
            "appearances": [1],
            "person": {
                "created_at": "2021-08-03T00:00:00Z",
                "distinct_ids": ["abc"],
                "id": ANY,
                "is_identified": False,
                "name": "abc",
                "properties": {},
                "uuid": ANY,
            },
        },
    ]
