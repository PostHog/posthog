import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

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
from posthog.models.team import Team
from posthog.test.base import stripResponse


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
        cohort = create_cohort_ok(
            client=client, team_id=team.id, name="test cohort", groups=[{"properties": {"cohort_identifier": 1}}]
        )

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
            request=TrendsRequestBreakdown(
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
            team=team,
        )

        assert stripResponse(trends["result"], remove=("persons_urls", "filter")) == [
            {
                "action": {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "name": "$pageview",
                    "custom_name": None,
                    "math": "dau",
                    "math_property": None,
                    "math_group_type_index": None,
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
        ]


@dataclass
class TrendsRequest:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    interval: Optional[str] = None
    insight: Optional[str] = None
    display: Optional[str] = None
    compare: Optional[bool] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    properties: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TrendsRequestBreakdown(TrendsRequest):
    breakdown: Optional[Union[List[int], str]] = None
    breakdown_type: Optional[str] = None


def get_trends(client, request: Union[TrendsRequestBreakdown, TrendsRequest], team: Team):
    data: Dict[str, Any] = {
        "date_from": request.date_from,
        "date_to": request.date_to,
        "interval": request.interval,
        "insight": request.insight,
        "display": request.display,
        "compare": request.compare,
        "events": json.dumps(request.events),
        "properties": json.dumps(request.properties),
    }

    if isinstance(request, TrendsRequestBreakdown):
        data["breakdown"] = request.breakdown
        data["breakdown_type"] = request.breakdown_type

    filtered_data = {k: v for k, v in data.items() if v is not None}

    return client.get(f"/api/projects/{team.id}/insights/trend/", data=filtered_data,)


def get_trends_ok(client: Client, request: TrendsRequest, team: Team):
    response = get_trends(client=client, request=request, team=team)
    assert response.status_code == 200, response.content
    return response.json()


@dataclass
class NormalizedTrendResult:
    value: float
    label: str
    person_url: str
    breakdown_value: Optional[Union[str, int]]


def get_trends_time_series_ok(
    client: Client, request: TrendsRequest, team: Team
) -> Dict[str, Dict[str, NormalizedTrendResult]]:
    data = get_trends_ok(client=client, request=request, team=team)
    return get_time_series_ok(data)


def get_time_series_ok(data):
    res = {}
    for item in data["result"]:
        collect_dates = {}
        for idx, date in enumerate(item["days"]):
            collect_dates[date] = NormalizedTrendResult(
                value=item["data"][idx],
                label=item["labels"][idx],
                person_url=item["persons_urls"][idx]["url"],
                breakdown_value=item.get("breakdown_value", None),
            )
        res[item["label"]] = collect_dates
    return res


def get_trends_aggregate_ok(client: Client, request: TrendsRequest, team: Team) -> Dict[str, NormalizedTrendResult]:
    data = get_trends_ok(client=client, request=request, team=team)
    res = {}
    for item in data["result"]:
        res[item["label"]] = NormalizedTrendResult(
            value=item["aggregated_value"],
            label=item["action"]["name"],
            person_url=item["persons"]["url"],
            breakdown_value=item.get("breakdown_value", None),
        )

    return res


def get_people_from_url_ok(client: Client, url: str):
    response = client.get("/" + url)
    assert response.status_code == 200, response.content
    return response.json()["results"][0]["people"]
