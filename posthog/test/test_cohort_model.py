import pytest

from posthog.client import sync_execute
from posthog.models import Cohort, Person, Team
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID
from posthog.test.base import BaseTest


class TestCohort(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False  # So that each test gets a different team_id, ensuring separation of CH data

    def test_insert_by_distinct_id_or_email(self):
        Person.objects.create(team=self.team, distinct_ids=["000"])
        Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team)
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, distinct_ids=["123"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.insert_users_by_list(["a header or something", "123", "000", "email@example.org"])
        cohort = Cohort.objects.get()
        self.assertEqual(cohort.people.count(), 2)
        self.assertEqual(cohort.is_calculating, False)

        #  If we accidentally call calculate_people it shouldn't erase people
        cohort.calculate_people_ch(pending_version=0)
        self.assertEqual(cohort.people.count(), 2)

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        cohort = Cohort.objects.get()
        self.assertEqual(cohort.people.count(), 2)
        self.assertEqual(cohort.is_calculating, False)

    @pytest.mark.ee
    def test_calculating_cohort_clickhouse(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        person1 = Person.objects.create(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        Person.objects.create(distinct_ids=["person2"], team_id=self.team.pk, properties={})
        person3 = Person.objects.create(
            distinct_ids=["person3"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        cohort.calculate_people_ch(pending_version=0)

        uuids = [
            row[0]
            for row in sync_execute(
                GET_COHORTPEOPLE_BY_COHORT_ID,
                {
                    "cohort_id": cohort.pk,
                    "team_id": self.team.pk,
                    "version": cohort.version,
                },
            )
        ]
        self.assertCountEqual(uuids, [person1.uuid, person3.uuid])

    def test_empty_query(self):
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}]}],
            name="cohort1",
        )

        cohort2.calculate_people_ch(pending_version=0)
        self.assertFalse(Cohort.objects.get().is_calculating)

    def test_group_to_property_conversion(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "something",
                            "type": "person",
                            "operator": "contains",
                        },
                        {"key": "other_prop", "value": "other_value", "type": "person"},
                    ]
                },
                {
                    "days": "4",
                    "count": "3",
                    "label": "$pageview",
                    "action_id": 1,
                    "count_operator": "eq",
                },
            ],
            name="cohort1",
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop",
                                "type": "person",
                                "value": "something",
                                "operator": "contains",
                            },
                            {
                                "key": "other_prop",
                                "type": "person",
                                "value": "other_value",
                            },
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": 1,
                                "type": "behavioral",
                                "value": "performed_event_multiple",
                                "event_type": "actions",
                                "operator": "eq",
                                "operator_value": 3,
                                "time_interval": "day",
                                "time_value": "4",
                            }
                        ],
                    },
                ],
            },
        )

    def test_group_to_property_conversion_with_valid_zero_count(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "something",
                            "type": "person",
                            "operator": "contains",
                        },
                        {"key": "other_prop", "value": "other_value", "type": "person"},
                    ]
                },
                {
                    "days": "4",
                    "count": "0",
                    "label": "$pageview",
                    "event_id": "$pageview",
                    "count_operator": "gte",
                },
            ],
            name="cohort1",
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop",
                                "type": "person",
                                "value": "something",
                                "operator": "contains",
                            },
                            {
                                "key": "other_prop",
                                "type": "person",
                                "value": "other_value",
                            },
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": 0,
                                "time_interval": "day",
                                "time_value": "4",
                            }
                        ],
                    },
                ],
            },
        )

    def test_group_to_property_conversion_with_valid_zero_count_different_operator(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "days": "4",
                    "count": "0",
                    "label": "$pageview",
                    "event_id": "$pageview",
                    "count_operator": "lte",
                }
            ],
            name="cohort1",
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "lte",
                                "operator_value": 0,
                                "time_interval": "day",
                                "time_value": "4",
                            }
                        ],
                    }
                ],
            },
        )

    def test_group_to_property_conversion_with_missing_days_and_invalid_count(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "count": -3,
                    "label": "$pageview",
                    "event_id": "$pageview",
                    "count_operator": "gte",
                }
            ],
            name="cohort1",
        )

        self.assertEqual(
            cohort.properties.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": 0,
                                "time_interval": "day",
                                "time_value": 365,
                            }
                        ],
                    }
                ],
            },
        )
