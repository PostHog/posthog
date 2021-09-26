import dataclasses
import json
from datetime import datetime
from typing import List, Optional

import pytest
from django.test import Client
from freezegun import freeze_time

from posthog.api.test.test_cohort import create_cohort_ok
from posthog.api.test.test_event_definition import EventData, capture_event
from posthog.api.test.test_retention import identify
from posthog.api.test.test_signup import signup_ok


def get_current_project(client: Client):
    return client.get("/api/projects/@current/")


def get_current_project_ok(client: Client):
    response = get_current_project(client=client)
    assert response.status_code == 200, response.content
    return response.json()


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
    signup_ok(client=client, email="user@fake.fake", password="password", organization_name="Hedgehogs United, LLC")
    project = get_current_project_ok(client=client)

    #  I'm creating a cohort here so that I can use as a breakdown, just because
    #  this is what was used demonstrated in
    #  https://github.com/PostHog/posthog/issues/2675 but it might not be the
    #  simplest way to reproduce
    cohort = create_cohort_ok(client=client, name="test cohort", groups=[{"properties": {"cohort_identifier": 1}}])

    # "2021-09-19" is a sunday, i.e. beginning of week
    with freeze_time("2021-09-20T16:00:00"):
        #  First identify as a member of the cohort
        distinct_id = "abc"
        identify(distinct_id=distinct_id, team_id=project["id"], properties={"cohort_identifier": 1})

        for date in ["2021-09-04", "2021-09-05", "2021-09-12", "2021-09-19"]:
            capture_event(
                event=EventData(
                    event="$pageview",
                    team_id=project["id"],
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
                breakdown=[cohort["id"]],
                breakdown_type="cohort",
                display="ActionsLineGraph",
                events=json.dumps(
                    [
                        {
                            "id": "$pageview",
                            "math": "dau",
                            "name": "$pageview",
                            "type": "events",
                            "order": 0,
                            "properties": [],
                            "math_property": None,
                        }
                    ]
                ),
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


@pytest.mark.django_db
@pytest.mark.ee
def test_math_is_functional(client: Client):
    """
    Regression test for https://github.com/PostHog/posthog/issues/4858

    The expectation of the frontend for certain values of `display` (here it is
    "ActionsTable") is to return a single aggregate value for each "action"
    aggregation requested. i.e. get me the number of distinct users who
    performed action x, over an arbitrary time range. This was all working fine,
    however, the frontend also performs some calculations, for example the mean
    of the number of distinct users by day. It was expecting a daily interval to
    do this, which we were not returning. We now always produce both the total
    value, and the interval breakdowns.

    NOTE: this was functioning as expected for postgresql as an events backend.
    """
    signup_ok(client=client, email="user@fake.fake", password="password", organization_name="Hedgehogs United, LLC")
    project = get_current_project_ok(client=client)

    # "2021-09-19" is a sunday, i.e. beginning of week
    with freeze_time("2021-09-20T16:00:00"):
        #  First identify as a member of the cohort
        distinct_id = "abc"
        identify(distinct_id=distinct_id, team_id=project["id"])

        capture_event(
            event=EventData(
                event="instance status report",
                team_id=project["id"],
                distinct_id=distinct_id,
                timestamp=datetime(2021, 9, 3),
                properties={"distinct_id": "abc", "teams__1__events_count_by_lib__posthog-python": "is_set"},
            )
        )

        event = {
            "id": "instance status report",
            "math": "dau",
            "name": "instance status report",
            "type": "events",
            "order": 0,
            "properties": [],
            "math_property": None,
        }

        trends = get_trends_ok(
            client,
            request=TrendsRequest(
                date_from="2021-09-3",
                date_to="2021-09-3",
                interval="day",
                insight="TRENDS",
                display="ActionsTable",
                funnel_window_days=14,
                events=json.dumps([event]),
            ),
        )

        assert trends == {
            "is_cached": False,
            "last_refresh": "2021-09-20T16:00:00Z",
            "next": None,
            "result": [
                {
                    "action": event,
                    "label": "instance status report",
                    "aggregated_value": 1,
                    "count": 1.0,
                    "data": [1.0],
                    # Prior to the fix this would also include '29-Aug-2021'
                    "labels": ["3-Sep-2021"],
                    "days": ["2021-09-03"],
                }
            ],
        }


@dataclasses.dataclass
class TrendsRequest:
    date_from: str
    date_to: str
    interval: str
    insight: str
    display: str
    # Events needs to be encoede as a json string
    events: str
    breakdown: Optional[List[int]] = None
    breakdown_type: Optional[str] = None
    funnel_window_days: Optional[int] = None


def get_trends(client, request: TrendsRequest):
    return client.get(
        "/api/insight/trend/",
        data={
            key: value
            for key, value in dataclasses.asdict(request).items()
            # Get rid of nulls as we can't encode these as urlencoding
            if value is not None
        },
    )


def get_trends_ok(client: Client, request: TrendsRequest):
    response = get_trends(client=client, request=request)
    assert response.status_code == 200, response.content
    return response.json()
