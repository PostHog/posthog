import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, List, TypedDict, Union

import pytest
from django.test import Client
from freezegun import freeze_time

from posthog.api.test.test_cohort import create_cohort_ok
from posthog.api.test.test_event_definition import (
    EventData,
    capture_event,
    create_organization,
    create_team,
    create_user,
)
from posthog.api.test.test_retention import identify


@pytest.mark.django_db
@pytest.mark.ee
def test_includes_only_intervals_within_range(client: Client):
    """
    This is the case highlighted by https://github.com/PostHog/posthog/issues/2675

    Here the issue is that we request, for instance, 14 days as the
    date_from, display at weekly intervals but previously we
    were displaying 4 ticks on the date axis. If we were exactly on the
    beginning of the week for two weeks then we'd want 2 ticks.
    Otherwise we would have 3 ticks as the range would be intersecting
    with three weeks. We should never need to display 4 ticks.
    """
    organization = create_organization(name="test org")
    team = create_team(organization=organization)
    user = create_user("user", "pass", organization)

    client.force_login(user)

    #  I'm creating a cohort here so that I can use as a breakdown, just because
    #  this is what was used demonstrated in
    #  https://github.com/PostHog/posthog/issues/2675 but it might not be the
    #  simplest way to reproduce

    # "2021-09-19" is a sunday, i.e. beginning of week
    with freeze_time("2021-09-20T16:00:00"):
        #  First identify as a member of the cohort
        distinct_id = "abc"
        identify(distinct_id=distinct_id, team_id=team.id, properties={"cohort_identifier": 1})
        cohort = create_cohort_ok(client=client, name="test cohort", groups=[{"properties": {"cohort_identifier": 1}}])

        for date in ["2021-09-04", "2021-09-05", "2021-09-12", "2021-09-19"]:
            capture_event(
                event=EventData(
                    event="$pageview",
                    team_id=team.id,
                    distinct_id=distinct_id,
                    timestamp=datetime.fromisoformat(date),
                    properties={"distinct_id": "abc"},
                )
            )

        trends = get_trends_ok(
            client,
            request=TrendsRequest(
                date_from="-14days",
                date_to="2021-09-21",
                interval="week",
                insight="TRENDS",
                breakdown=json.dumps([cohort["id"]]),
                breakdown_type="cohort",
                display="ActionsLineGraph",
                events=[
                    {
                        "id": "$pageview",
                        "math": "dau",
                        "name": "$pageview",
                        "custom_name": None,
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_property": None,
                    }
                ],
            ),
        )
        assert trends == {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "result": [
                {
                    "action": {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": None,
                        "math": "dau",
                        "math_property": None,
                        "properties": [],
                    },
                    "breakdown_value": cohort["id"],
                    "label": "$pageview - test cohort",
                    "count": 3.0,
                    "data": [1.0, 1.0, 1.0],
                    # Prior to the fix this would also include '29-Aug-2021'
                    "labels": ["5-Sep-2021", "12-Sep-2021", "19-Sep-2021"],
                    "days": ["2021-09-05", "2021-09-12", "2021-09-19"],
                }
            ],
        }


@dataclasses.dataclass
class TrendsRequest:
    date_from: str
    date_to: str
    interval: str
    insight: str
    breakdown: Union[List[int], str]
    breakdown_type: str
    display: str
    events: List[Dict[str, Any]]


def get_trends(client, request: TrendsRequest):
    return client.get(
        "/api/insight/trend/",
        data={
            "date_from": request.date_from,
            "date_to": request.date_to,
            "interval": request.interval,
            "insight": request.insight,
            "breakdown": request.breakdown,
            "breakdown_type": request.breakdown_type,
            "display": request.display,
            "events": json.dumps(request.events),
        },
    )


def get_trends_ok(client: Client, request: TrendsRequest):
    response = get_trends(client=client, request=request)
    assert response.status_code == 200, response.content
    return response.json()
