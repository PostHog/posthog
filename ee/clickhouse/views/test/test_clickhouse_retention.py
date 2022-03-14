from dataclasses import asdict, dataclass
from typing import List, Literal, Optional, TypedDict, Union

from constance.test import override_config
from django.test import TestCase
from django.test.client import Client

from ee.clickhouse.test.test_journeys import _create_all_events, update_or_create_person
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from ee.clickhouse.views.test.funnel.util import EventPattern
from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.test.base import test_with_materialized_columns
from posthog.utils import encode_get_request_params


class RetentionTests(TestCase, ClickhouseTestMixin):
    @snapshot_clickhouse_queries
    def test_retention_test_account_filters(self):

        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        team.test_account_filters = [
            {"key": "email", "type": "person", "value": "posthog.com", "operator": "not_icontains"}
        ]
        team.save()

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk, properties={"email": "posthog.com"})
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 3"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
                "2020-01-02": {"person 1": [{"event": "target event"}], "person 3": [{"event": "target event"}]},
                "2020-01-03": {"person 1": [{"event": "target event"}], "person 3": [{"event": "target event"}]},
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
                period="Day",
                retention_type="retention_first_time",
                filter_test_accounts="true",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_for_response(client=self.client, response=retention)

        assert retention_by_cohort_by_period == {
            "Day 0": {"1": ["person 2"], "2": [],},
            "Day 1": {"1": ["person 3"]},
        }

    @snapshot_clickhouse_queries
    def test_retention_aggregation_by_distinct_id_and_retrieve_people(self):
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        p1 = update_or_create_person(distinct_ids=["person 1", "another one"], team_id=team.pk)
        p2 = update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event",}], "another one": [{"event": "target event",}],},
                "2020-01-02": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
                "2020-01-03": {"another one": [{"event": "target event"}],},
            },
            team=team,
        )

        with override_config(AGGREGATE_BY_DISTINCT_IDS_TEAMS=f"{team.pk}"):
            retention = get_retention_ok(
                client=self.client,
                team_id=team.pk,
                request=RetentionRequest(
                    target_entity={"id": "target event", "type": "events"},
                    returning_entity={"id": "target event", "type": "events"},
                    date_from="2020-01-01",
                    total_intervals=3,
                    date_to="2020-01-03",
                    period="Day",
                    retention_type="retention_first_time",
                ),
            )

            assert retention["result"][0]["values"][0]["count"] == 2  #  person 1 and another one
            assert retention["result"][0]["values"][1]["count"] == 1  # person 1
            assert retention["result"][0]["values"][2]["count"] == 1  # another one

            #  person 2
            assert retention["result"][1]["values"][0]["count"] == 1
            assert retention["result"][1]["values"][1]["count"] == 0

            people_url = retention["result"][0]["values"][0]["people_url"]
            people_response = self.client.get(people_url)
            assert people_response.status_code == 200

            people = people_response.json()["result"]
            # person1 and another one are the same person
            assert len(people) == 1
            assert people[0]["id"] == str(p1.uuid)

            people_url = retention["result"][1]["values"][0]["people_url"]
            people_response = self.client.get(people_url)
            assert people_response.status_code == 200

            people = people_response.json()["result"]
            assert len(people) == 1
            assert people[0]["id"] == str(p2.uuid)


class BreakdownTests(TestCase, ClickhouseTestMixin):
    def test_can_get_retention_cohort_breakdown(self):
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 3"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
                "2020-01-02": {"person 1": [{"event": "target event"}], "person 3": [{"event": "target event"}]},
                "2020-01-03": {"person 1": [{"event": "target event"}], "person 3": [{"event": "target event"}]},
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
                period="Day",
                retention_type="retention_first_time",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_for_response(client=self.client, response=retention)

        assert retention_by_cohort_by_period == {
            "Day 0": {"1": ["person 1", "person 2"], "2": ["person 1"],},
            "Day 1": {"1": ["person 3"]},
        }

    def test_can_get_retention_cohort_breakdown_with_retention_type_target(self):
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 3"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
                "2020-01-02": {"person 1": [{"event": "target event"}], "person 3": [{"event": "target event"}]},
                "2020-01-03": {"person 1": [{"event": "target event"}], "person 3": [{"event": "target event"}]},
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
                period="Day",
                retention_type="retention",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_for_response(client=self.client, response=retention)

        assert retention_by_cohort_by_period == {
            "Day 0": {"1": ["person 1", "person 2"], "2": ["person 1"],},
            "Day 1": {"1": ["person 3", "person 1"]},
        }

    @test_with_materialized_columns(person_properties=["os"])
    def test_can_specify_breakdown_person_property(self):
        """
        By default, we group users together by the first time they perform the
        `target_event`. However, we should also be able to specify, e.g. the
        users OS to be able to compare retention between the OSs.
        """
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk, properties={"os": "Chrome"})
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk, properties={"os": "Safari"})

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event"}]},
                "2020-01-02": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
                # IMPORTANT: we include data past the end of the requested
                # window, as we want to ensure that we pick up all retention
                # periods for a user. e.g. for "person 2" we do not want to miss
                # the count from 2020-01-03 e.g. the second period, otherwise we
                # will skew results for users that didn't perform their target
                # event right at the beginning of the requested range.
                "2020-01-03": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
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
                period="Day",
                retention_type="retention_first_time",
                breakdowns=[Breakdown(type="person", property="os")],
                # NOTE: we need to specify breakdown_type as well, as the
                # breakdown logic currently does not support multiple differing
                # types
                breakdown_type="person",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_for_response(client=self.client, response=retention)

        assert retention_by_cohort_by_period, {
            "Chrome": {"1": ["person 1"], "2": ["person 1"]},
            "Safari": {
                "1": ["person 2"],
                "2": ["person 2"],
            },  # IMPORTANT: the "2" value is from past the requested `date_to`
        }

    @test_with_materialized_columns(event_properties=["os"])
    def test_can_specify_breakdown_event_property(self):
        """
        By default, we group users together by the first time they perform the
        `target_event`. However, we should also be able to specify, e.g. the
        users OS to be able to compare retention between the OSs.
        """
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event", "properties": {"os": "Chrome"}}]},
                "2020-01-02": {
                    "person 1": [{"event": "target event"}],
                    "person 2": [{"event": "target event", "properties": {"os": "Safari"}}],
                },
                # IMPORTANT: we include data past the end of the requested
                # window, as we want to ensure that we pick up all retention
                # periods for a user. e.g. for "person 2" we do not want to miss
                # the count from 2020-01-03 e.g. the second period, otherwise we
                # will skew results for users that didn't perform their target
                # event right at the beginning of the requested range.
                "2020-01-03": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}]},
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
                period="Day",
                retention_type="retention_first_time",
                breakdowns=[Breakdown(type="event", property="os")],
                # NOTE: we need to specify breakdown_type as well, as the
                # breakdown logic currently does not support multiple differing
                # types
                breakdown_type="event",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_for_response(client=self.client, response=retention)

        assert retention_by_cohort_by_period == {
            "Chrome": {"1": ["person 1"], "2": ["person 1"]},
            "Safari": {
                "1": ["person 2"],
                "2": ["person 2"],
            },  # IMPORTANT: the "2" value is from past the requested `date_to`
        }

    @test_with_materialized_columns(event_properties=["os"])
    def test_can_specify_breakdown_event_property_and_retrieve_people(self):
        """
        This test is slightly different from the
        get_by_cohort_by_period_for_response based tests in that here we are
        checking a cohort/period specific people url that does not include the
        "appearances" detail.

        This is used, e.g. for the frontend retentions trend graph
        """
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {
                    "person 1": [{"event": "target event", "properties": {"os": "Chrome"}}],
                    "person 2": [{"event": "target event", "properties": {"os": "Safari"}}],
                },
                "2020-01-02": {"person 1": [{"event": "target event"}], "person 2": [{"event": "target event"}],},
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
                period="Day",
                retention_type="retention_first_time",
                breakdowns=[Breakdown(type="event", property="os")],
                # NOTE: we need to specify breakdown_type as well, as the
                # breakdown logic currently does not support multiple differing
                # types
                breakdown_type="event",
            ),
        )

        chrome_cohort = [cohort for cohort in retention["result"] if cohort["label"] == "Chrome"][0]
        people_url = chrome_cohort["values"][0]["people_url"]
        people_response = self.client.get(people_url)
        assert people_response.status_code == 200

        people = people_response.json()["result"]

        assert [distinct_id for person in people for distinct_id in person["distinct_ids"]] == ["person 1"]


class IntervalTests(TestCase, ClickhouseTestMixin):
    def test_can_get_retention_week_interval(self):
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        update_or_create_person(distinct_ids=["person 1"], team_id=team.pk)
        update_or_create_person(distinct_ids=["person 2"], team_id=team.pk)

        setup_user_activity_by_day(
            daily_activity={
                "2020-01-01": {"person 1": [{"event": "target event"}]},
                "2020-01-08": {"person 2": [{"event": "target event"}]},
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
                date_to="2020-01-08",
                period="Week",
                retention_type="retention_first_time",
            ),
        )

        retention_by_cohort_by_period = get_by_cohort_by_period_for_response(client=self.client, response=retention)

        assert retention_by_cohort_by_period == {
            "Week 0": {"1": ["person 1"], "2": [],},
            "Week 1": {"1": ["person 2"]},
        }


class RegressionTests(TestCase, ClickhouseTestMixin):
    def test_can_get_actors_and_use_percent_char_filter(self):
        """
        References https://github.com/PostHog/posthog/issues/7747

        Essentially we were performing a double string substitution, which
        causes issues if, in that case, we use a string substitution that
        includes a '%' character, and then run substitution again.

        This was the case for instance when you wanted to filter out test users
        e.g. by postgres LIKE matching '%posthog.com%'
        """
        organization = create_organization(name="test")
        team = create_team(organization=organization)
        user = create_user(email="test@posthog.com", password="1234", organization=organization)

        self.client.force_login(user)

        response = get_retention_people(
            client=self.client,
            team_id=team.pk,
            request=RetentionRequest(
                target_entity={"id": "target event", "type": "events"},
                returning_entity={"id": "target event", "type": "events"},
                date_from="2020-01-01",
                total_intervals=2,
                date_to="2020-01-08",
                period="Week",
                retention_type="retention_first_time",
                properties=[{"key": "email", "value": "posthog.com", "operator": "not_icontains", "type": "person"}],
            ),
        )

        assert response.status_code == 200


def setup_user_activity_by_day(daily_activity, team):
    _create_all_events(
        [
            {"distinct_id": person_id, "team": team, "timestamp": timestamp, **event}
            for timestamp, people in daily_activity.items()
            for person_id, events in people.items()
            for event in events
        ]
    )


@dataclass(frozen=True)
class Breakdown:
    type: str
    property: str


class PropertyFilter(TypedDict):
    key: str
    value: str
    operator: Literal["not_icontains"]  # NOTE: not exhaustive
    type: Literal["person"]  # NOTE: not exhaustive


@dataclass(frozen=True)
class RetentionRequest:
    date_from: str  # From what I can tell, this doesn't do anything, rather `total_intervals` is used
    total_intervals: int
    date_to: str
    target_entity: EventPattern
    returning_entity: EventPattern
    period: Union[Literal["Hour"], Literal["Day"], Literal["Week"], Literal["Month"]]
    retention_type: Literal["retention_first_time", "retention"]  # probably not an exhaustive list

    breakdowns: Optional[List[Breakdown]] = None
    breakdown_type: Optional[Literal["person", "event"]] = None

    properties: Optional[List[PropertyFilter]] = None
    filter_test_accounts: Optional[str] = None


class Value(TypedDict):
    count: int
    people_url: str


class Cohort(TypedDict):
    values: List[Value]
    date: str
    label: str


class RetentionResponse(TypedDict):
    result: List[Cohort]


class Person(TypedDict):
    distinct_ids: List[str]


class RetentionTableAppearance(TypedDict):
    person: Person
    appearances: List[int]


class RetentionTablePeopleResponse(TypedDict):
    result: List[RetentionTableAppearance]


def get_retention_ok(client: Client, team_id: int, request: RetentionRequest) -> RetentionResponse:
    response = get_retention(client=client, team_id=team_id, request=request)
    assert response.status_code == 200, response.content
    return response.json()


def get_retention(client: Client, team_id: int, request: RetentionRequest):
    return client.get(
        f"/api/projects/{team_id}/insights/retention/",
        # NOTE: for get requests we need to JSON encode non-scalars
        data=encode_get_request_params(asdict(request)),
    )


def get_retention_people(client: Client, team_id: int, request: RetentionRequest):
    return client.get(
        f"/api/person/retention/",
        # NOTE: for get requests we need to JSON encode non-scalars
        data=encode_get_request_params(asdict(request)),
    )


def get_retention_table_people_from_url_ok(client: Client, people_url: str):
    response = client.get(people_url)
    assert response.status_code == 200
    return response.json()


def get_by_cohort_by_period_for_response(client: Client, response: RetentionResponse):
    """
    Helper that, given a retention response, will fetch all corresponding distinct ids
    and return in the format:

    ```
        {
            "<cohort-label>": {
                "1": ["person 1", ...]
                "2": [...]
                ...
            }
            ...
        }
    ```
    """

    def create_cohort_period(people, period, value):
        people_in_period = [
            distinct_id
            for person in people
            for distinct_id in person["person"]["distinct_ids"]
            if person["appearances"][period]
        ]

        # Check the count is the same as the people size. We don't handle any
        # pagination so this could be wrong for large counts
        assert value["count"] == len(people_in_period)

        return people_in_period

    def create_cohort_response(cohort):
        people = get_retention_table_people_from_url_ok(client=client, people_url=cohort["people_url"])["result"]

        return {
            f"{period + 1}": create_cohort_period(people, period, value)
            for period, value in enumerate(cohort["values"])
        }

    return {cohort["label"]: create_cohort_response(cohort) for cohort in response["result"]}


def get_by_cohort_by_period_from_response(response: RetentionResponse):
    return {
        cohort["label"]: {f"{period + 1}": value["count"] for period, value in enumerate(cohort["values"])}
        for cohort in response["result"]
    }
