from datetime import datetime
from typing import Any

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.test.test_journeys import journeys_for, update_or_create_person
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.api.test.test_trends import TrendsRequest, get_people_from_url_ok, get_trends_ok
from posthog.test.base import APIBaseTest, test_with_materialized_columns


class ClickhouseTestReservedEventAttributes(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    maxDiff = None
    CLASS_DATA_LEVEL_SETUP = False

    def _create_timestamped_data(self) -> None:
        """
        We can now make datetime aware filters using both
         - keys in the properties blob
         - or the events' table timestamp column
        """
        events_by_person = {
            "p1": [
                {"event": "$pageview", "timestamp": datetime(2020, 1, 2, 3), "properties": {"a_date": "2021-04-01"}},
            ],
            "p2": [
                {"event": "$pageview", "timestamp": datetime(2020, 1, 2, 4), "properties": {"a_date": "2021-04-03"}}
            ],
            "p3": [
                {
                    "event": "$pageview",
                    "timestamp": datetime(2020, 1, 2, 3, 45),
                    "properties": {"a_date": "2021-04-01"},
                },
            ],
        }

        journeys_for(events_by_person, self.team)

    def _make_trends_request(self, properties) -> Any:
        response_json = get_trends_ok(
            client=self.client,
            request=TrendsRequest(
                date_from="2020-01-02T00:00:00Z",
                date_to="2020-01-02T00:00:00Z",
                events=[{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                properties=properties,
            ),
            team=self.team,
        )
        return response_json

    def test_can_filter_trends_by_event_timestamp(self):
        """
        Regression test for https://github.com/PostHog/posthog/pull/8340

        Querying event table columns 'distinct_id' from a property filter was breaking person property look-up
        """
        self._create_timestamped_data()

        response = self._make_trends_request(
            [{"key": "timestamp", "value": "2020-01-02 03:46:00", "operator": "is_date_after", "type": "event"}]
        )

        people = get_people_from_url_ok(client=self.client, url=response["result"][0]["persons_urls"][0]["url"])
        assert {distinct_id for person in people for distinct_id in person["distinct_ids"]} == {"p2"}

    @test_with_materialized_columns(["a_date"])
    def test_can_filter_trends_by_event_property_holding_a_datetime(self):
        self._create_timestamped_data()

        response = self._make_trends_request(
            [{"key": "a_date", "value": "2021-04-02 03:30:00", "operator": "is_date_before", "type": "event"},]
        )

        people = get_people_from_url_ok(client=self.client, url=response["result"][0]["persons_urls"][0]["url"])
        assert {distinct_id for person in people for distinct_id in person["distinct_ids"]} == {"p1", "p3"}

    def test_can_filter_trends_by_event_property_holding_a_datetime_and_timestamp(self):
        self._create_timestamped_data()

        response = self._make_trends_request(
            [
                {"key": "a_date", "value": "2021-04-02 03:30:00", "operator": "is_date_before", "type": "event"},
                {"key": "timestamp", "value": "2020-01-02 03:00:00", "operator": "is_date_after", "type": "event"},
            ]
        )

        people = get_people_from_url_ok(client=self.client, url=response["result"][0]["persons_urls"][0]["url"])
        assert {distinct_id for person in people for distinct_id in person["distinct_ids"]} == {"p3"}

    @test_with_materialized_columns(person_properties=["timestamp"])
    def test_can_filter_on_person_property_called_timestamp(self):
        update_or_create_person(distinct_ids=["p1"], team_id=self.team.pk, properties={"timestamp": "2035-04-01"})
        self._create_timestamped_data()

        response = self._make_trends_request(
            [{"key": "timestamp", "value": "2035-01-01", "operator": "is_date_after", "type": "person"}]
        )

        people = get_people_from_url_ok(client=self.client, url=response["result"][0]["persons_urls"][0]["url"])
        assert {distinct_id for person in people for distinct_id in person["distinct_ids"]} == {"p1"}

    @test_with_materialized_columns(["distinct_id"])
    def test_regression_on_filtering_on_distinct_id(self):
        # Regression test for
        # https://sentry.io/organizations/posthog2/issues/2968014180/?project=1899813&query=is%3Aunresolved+CHQueryErrorAmbiguousColumnName&statsPeriod=14d
        #
        # This [PR](https://github.com/PostHog/posthog/pull/8291/files) resulted
        # in a nambiguous reference to distinct_id, when distinct_id was
        # filtered as a person property.
        #
        # NOTE: This tests that we can filter for the distinct_id on persons,
        # which is a little ambiguous between if you want to look for a
        # distinct_id in person properties, or an associated distinct_id to a
        # person. As of writing it is the former.
        #
        # At time of writing only two teams have distinct_id in person properties
        # And only on a small percentage of persons
        update_or_create_person(distinct_ids=["p1"], team_id=self.team.pk, properties={"distinct_id": "person1"})
        update_or_create_person(distinct_ids=["p2"], team_id=self.team.pk, properties={"distinct_id": "person2"})
        self._create_timestamped_data()

        response = self._make_trends_request(
            [{"key": "distinct_id", "value": "person1", "operator": "ncontains", "type": "person"}]
        )

        people = get_people_from_url_ok(client=self.client, url=response["result"][0]["persons_urls"][0]["url"])
        assert {distinct_id for person in people for distinct_id in person["distinct_ids"]} == {"p1"}
