import json
import numbers
from datetime import datetime, timedelta
from typing import List, Literal, TypedDict, Union

from django.test import TestCase
from django.test.client import Client

from ee.clickhouse.test.test_journeys import _create_all_events, update_or_create_person
from ee.clickhouse.views.test.funnel.util import EventPattern
from posthog.api.test.test_event import get_events_ok
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user


class RetentionTests(TestCase):
    def test_retention_includes_periods_past_requested_date_to_if_before_now(self):
        """
        Typically we display cohort analysis as a top left triangle, as if we
        are looking at cohorts up to today, we do not have subsequent periods
        for all cohorts available (they are in the future).  However, say we
        specify date_to in the past. In this case we should be able to get more
        periods.

        Main driver here is to be able to specify a past date and to be able to
        get a nice "J-Curve" line graph, which doesn't have all periods.
        """

        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        events = user_activity_by_day(
            daily_activity={
                "2020-01-01": ["person 1", "person 2"],
                "2020-01-02": ["person 1", "person 3"],
                "2020-01-03": ["person 1", "person 3"],
            },
            target_event="target event",
            returning_event="target event",
            team=team,
        )

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 3"], team_id=team.pk)
        _create_all_events(all_events=events)

        retention = get_retention_ok(
            client=self.client,
            team_id=team.pk,
            request=RetentionRequest(
                target_entity={"id": "target event", "type": "events"},
                returning_entity={"id": "target event", "type": "events"},
                date_from="2020-01-01",
                total_intervals=2,
                date_to="2020-01-02",
                period="Day",
                retention_type="retention_first_time",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_from_response(response=retention)

        assert retention_by_cohort_by_period == {
            "2020-01-01": {"2020-01-01": 2, "2020-01-02": 1,},  # ["person 1", "person 2"]  # ["person 1"]
            "2020-01-02": {"2020-01-02": 1, "2020-01-03": 1,},  # ["person 3"]  # ["person 3"]
        }


def user_activity_by_day(daily_activity, target_event, returning_event, team):
    return [
        {"distinct_id": person_id, "team": team, "timestamp": timestamp, "event": target_event}
        for timestamp, people in daily_activity.items()
        for person_id in people
    ]


class RetentionRequest(TypedDict):
    date_from: str  # From what I can tell, this doesn't do anything, rather `total_intervals` is used
    total_intervals: int
    date_to: str
    target_entity: EventPattern
    returning_entity: EventPattern
    period: Union[Literal["Hour"], Literal["Day"], Literal["Week"], Literal["Month"]]
    retention_type: Literal["retention_first_time"]  # probably not an exhaustive list


class Value(TypedDict):
    count: int


class Cohort(TypedDict):
    values: List[Value]
    date: str
    label: str


class RetentionResponse(TypedDict):
    result: List[Cohort]


def get_retention_ok(client: Client, team_id: int, request: RetentionRequest) -> RetentionResponse:
    response = get_retention(client=client, team_id=team_id, request=request)
    assert response.status_code == 200, response.content
    return response.json()


def get_retention(client: Client, team_id: int, request: RetentionRequest):
    return client.get(
        f"/api/projects/{team_id}/insights/retention/",
        # NOTE: for get requests we need to JSON encode non-scalars
        data={k: (v if isinstance(v, (str, numbers.Number)) else json.dumps(v)) for k, v in request.items()},
    )


def get_by_cohort_by_period_from_response(response: RetentionResponse):
    return {
        cohort["date"][:10]: {
            datetime.isoformat(datetime.fromisoformat(cohort["date"][:10]) + timedelta(days=1))[:10]: value["count"]
            for period, value in enumerate(cohort["values"])
        }
        for cohort in response["result"]
    }
