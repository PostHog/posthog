import json
import numbers
from typing import List, Literal, TypedDict, Union

from django.test import TestCase
from django.test.client import Client

from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.views.test.funnel.util import EventPattern
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user


class RetentionTests(TestCase):
    def test_can_get_line_chart_and_fetch_people(self):
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        journeys_for(
            events_by_person={
                "person that stays forever": [
                    {"event": "target event", "timestamp": "2020-01-01"},
                    {"event": "target event", "timestamp": "2020-01-02"},
                ],
                "person that leaves on 2020-01-02": [{"event": "target event", "timestamp": "2020-01-01"}],
            },
            team=team,
        )

        retention = get_retention_ok(
            client=self.client,
            team_id=team.pk,
            request=RetentionRequest(
                target_entity={"id": "target event", "type": "events"},
                returning_entity={"id": "target event", "type": "events"},
                date_from="2020-01-01",
                total_intervals=2,
                date_to="2020-01-02",
                display="ActionsLineGraph",
                period="Day",
                retention_type="retention_first_time",
            ),
        )

        trend_series = retention["result"][0]
        retention_by_day = get_people_for_retention_trend_series(client=self.client, trend_series=trend_series)

        assert retention_by_day == {
            "2020-01-01": ["person that leaves on 2020-01-02", "person that stays forever"],
            "2020-01-02": ["person that stays forever"],
        }

    def test_can_create_cohorts_from_retention_cohorts(self):
        """
        This is primarily such that we can then easily explore cohorts that we
        think are or interest.

        For each retention cohort we want to be able to 1. see the people in the
        cohort, and 2. save the people as a cohort to be used elsewhere in the
        system.
        """
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        journeys_for(
            events_by_person={
                "person that stays forever": [
                    {"event": "target event", "timestamp": "2020-01-01"},
                    {"event": "target event", "timestamp": "2020-01-02"},
                ],
                "person that leaves on 2020-01-02": [{"event": "target event", "timestamp": "2020-01-01"}],
            },
            team=team,
        )

        retention = get_retention_ok(
            client=self.client,
            team_id=team.pk,
            request=RetentionRequest(
                target_entity={"id": "target event", "type": "events"},
                returning_entity={"id": "target event", "type": "events"},
                date_from="2020-01-01",
                total_intervals=2,
                date_to="2020-01-02",
                display="",
                period="Day",
                retention_type="retention_first_time",
            ),
        )

        cohort_results = retention["result"]
        retention_by_day = get_people_for_retention_cohorts(client=self.client, cohort_results=cohort_results)

        assert retention_by_day == {
            "2020-01-01": ["person that leaves on 2020-01-02", "person that stays forever"],
            "2020-01-02": ["person that stays forever"],
        }


class RetentionRequest(TypedDict):
    date_from: str  # From what I can tell, this doesn't do anything, rather `total_intervals` is used
    total_intervals: int
    date_to: str
    target_entity: EventPattern
    returning_entity: EventPattern
    period: Union[Literal["Hour"], Literal["Day"], Literal["Week"], Literal["Month"]]
    retention_type: Literal["retention_first_time"]  # probably not an exhaustive list
    display: Literal["ActionsLineGraph", ""]


class Series(TypedDict):
    days: List[str]
    data: List[int]

    # List of people urls corresponding to `data`
    people_urls: List[str]


class RetentionTrendResponse(TypedDict):
    result: List[Series]


class Cohort(TypedDict):
    label: str
    people_url: str


class RetentionCohortsResponse(TypedDict):
    result: List[Cohort]


def get_retention_ok(client: Client, team_id: int, request: RetentionRequest):
    response = get_retention(client=client, team_id=team_id, request=request)
    assert response.status_code == 200, response.content
    return response.json()


def get_retention(client: Client, team_id: int, request: RetentionRequest):
    return client.get(
        f"/api/projects/{team_id}/insights/retention/",
        # NOTE: for get requests we need to JSON encode non-scalars
        data={k: (v if isinstance(v, (str, numbers.Number)) else json.dumps(v)) for k, v in request.items()},
    )


def get_people_for_retention_trend_series(client: Client, trend_series: Series):
    def get_people_ids_via_url(people_url):
        response = client.get(people_url)
        assert response.status_code == 200, response.content
        return sorted([distinct_id for person in response.json()["result"] for distinct_id in person["distinct_ids"]])

    return {
        day: get_people_ids_via_url(people_url) if count else []
        for day, count, people_url in zip(trend_series["days"], trend_series["data"], trend_series["people_urls"])
    }


def get_people_for_retention_cohorts(client: Client, cohort_results: List[Cohort]):
    def get_people_ids_via_url(people_url):
        response = client.get(people_url)
        assert response.status_code == 200, response.content
        return sorted([distinct_id for person in response.json()["result"] for distinct_id in person["distinct_ids"]])

    return {
        cohort_result["label"]: get_people_ids_via_url(cohort_result["people_url"]) for cohort_result in cohort_results
    }
