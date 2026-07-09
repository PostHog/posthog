import uuid
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest

from django.test import override_settings

from celery.exceptions import SoftTimeLimitExceeded
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.helpers.batch_iterators import FunctionBatchIterator
from posthog.models import Person, Team
from posthog.models.person.util import get_person_by_id
from posthog.test.persons import add_cohort_members, create_person

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.sql import GET_COHORTPEOPLE_BY_COHORT_ID
from products.cohorts.backend.models.util import count_cohort_members, list_cohort_member_ids
from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType


def _require_person_by_id(team_id: int, person_id: int) -> Person:
    person = get_person_by_id(team_id, person_id)
    assert person is not None
    return person


class TestCohort(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False  # So that each test gets a different team_id, ensuring separation of CH data

    def test_insert_by_distinct_id(self):
        create_person(team=self.team, distinct_ids=["000"])
        create_person(team=self.team, distinct_ids=["123"])
        create_person(team=self.team)
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        create_person(team=team2, distinct_ids=["123"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.insert_users_by_list(["a header or something", "123", "000", "email@example.org"])
        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.id, cohort.pk), 2)
        self.assertEqual(cohort.is_calculating, False)

        #  If we accidentally call calculate_people it shouldn't erase people
        cohort.calculate_people_ch(pending_version=0)
        self.assertEqual(count_cohort_members(self.team.id, cohort.pk), 2)

        # if we add people again, don't increase the number of people in cohort
        cohort.insert_users_by_list(["123"])
        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.id, cohort.pk), 2)
        self.assertEqual(cohort.is_calculating, False)

    def test_insert_by_distinct_id_in_batches(self):
        create_person(team=self.team, distinct_ids=["000"])
        create_person(team=self.team, distinct_ids=["001"])
        create_person(team=self.team, distinct_ids=["002", "011"])
        create_person(team=self.team, distinct_ids=["003", "012"])
        create_person(team=self.team, distinct_ids=["004"])
        create_person(team=self.team, distinct_ids=["005"])
        create_person(team=self.team, distinct_ids=["006"])
        create_person(team=self.team, distinct_ids=["007"])
        create_person(team=self.team, distinct_ids=["008"])
        create_person(team=self.team, distinct_ids=["009"])
        create_person(team=self.team, distinct_ids=["010"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        batch_count = cohort.insert_users_by_list(
            ["000", "001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"], batch_size=3
        )
        self.assertEqual(batch_count, 5)
        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.id, cohort.pk), 11)
        self.assertEqual(cohort.is_calculating, False)

    @pytest.mark.ee
    def test_calculating_cohort_clickhouse(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        person1 = create_person(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        create_person(distinct_ids=["person2"], team_id=self.team.pk, properties={})
        person3 = create_person(
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
        cohort2.refresh_from_db()
        self.assertFalse(cohort2.is_calculating)

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

    def test_insert_users_list_by_uuid(self):
        # These are some fine uuids.
        uuids = [
            "96757a52-a170-4cbb-ad49-a713c20b56e0",
            "74615ff4-1573-45b7-98ca-9897df0f8332",
            "0cbdd9c3-be93-4291-b721-2dbba2093f62",
            "243103c3-b41a-4c81-89d1-59c61f36244c",
            "85167c43-e611-4442-be3c-ede1e1788b6a",
            "8f926bdd-29e8-4b6f-8eda-053e9ef0c4ec",
            "8a3954b6-61f6-429f-ad8a-65db1e2728a9",
            "d2d26447-8700-422d-99ad-c37b5fb6602a",
            "0c386ba6-6307-460f-90b3-0f0ed0aee893",
            "fe3876bc-c75c-4c79-ae55-2af6892b9da7",
            "345b621a-26e1-4888-a9eb-175329f7923b",
        ]
        for person_uuid in uuids:
            create_person(team=self.team, uuid=person_uuid)
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)

        # Insert all users into the cohort using batching (batchsize=3)
        cohort.insert_users_list_by_uuid(items=uuids, team_id=self.team.id, batchsize=3)

        # Fetch all persons in the cohort
        cohort.refresh_from_db()
        assert cohort.count == 11
        assert count_cohort_members(self.team.id, cohort.pk) == 11
        member_ids = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.pk)
        cohort_person_uuids = {str(_require_person_by_id(self.team.id, pid).uuid) for pid in member_ids}
        assert cohort_person_uuids == set(uuids)

    def test_insert_users_list_by_id_uuid_pairs(self):
        persons = [create_person(team=self.team) for _ in range(5)]
        pairs = [(person.id, str(person.uuid)) for person in persons]
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)

        cohort.insert_users_list_by_id_uuid_pairs(pairs, team_id=self.team.id)

        cohort.refresh_from_db()
        assert cohort.count == 5
        assert set(list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.pk)) == {p.id for p in persons}
        # The members must also land in the ClickHouse static cohort table, keyed by uuid.
        ch_rows = sync_execute(
            "SELECT person_id FROM person_static_cohort WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
            {"team_id": self.team.id, "cohort_id": cohort.pk},
        )
        assert {str(row[0]) for row in ch_rows} == {str(p.uuid) for p in persons}
        assert cohort.is_calculating is False

    def test_insert_users_by_list_avoids_duplicates_with_batching(self):
        """Test that batching with duplicates works correctly - people already in cohort are not re-inserted."""
        # Create people with distinct IDs
        for i in range(10):
            create_person(team=self.team, distinct_ids=[f"user{i}"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)

        # First insertion - add users 0-4 (batch size 3 will create batches: [0,1,2], [3,4])
        cohort.insert_users_by_list(["user0", "user1", "user2", "user3", "user4"], batch_size=3)
        cohort.refresh_from_db()
        self.assertEqual(count_cohort_members(self.team.id, cohort.pk), 5)

        # Second insertion - try to add users 2-7 (users 2,3,4 are already in cohort)
        # This tests that our LEFT JOIN optimization works across batch boundaries
        cohort.insert_users_by_list(["user2", "user3", "user4", "user5", "user6", "user7"], batch_size=3)
        cohort.refresh_from_db()

        # Should have 8 people total (user0-user7) - no duplicates
        self.assertEqual(count_cohort_members(self.team.id, cohort.pk), 8)

        # Verify all expected people are in the cohort
        cohort_person_distinct_ids: set[str] = set()
        for pid in list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.pk):
            cohort_person_distinct_ids.update(_require_person_by_id(self.team.id, pid).distinct_ids)

        expected_distinct_ids = {f"user{i}" for i in range(8)}
        self.assertEqual(cohort_person_distinct_ids, expected_distinct_ids)

        # Verify the cohort is not in calculating state
        self.assertFalse(cohort.is_calculating)

    def test_insert_users_list_by_uuid_with_different_db_aliases(self):
        from unittest.mock import patch

        person = create_person(team=self.team, distinct_ids=["cross-db-test"])
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)

        # Simulate production config where db_for_read returns a different
        # alias than db_for_write. Both "default" and "persons_db_writer"
        # resolve to the same test database, but Django treats them as
        # different DBs and rejects cross-DB subqueries.
        with patch("django.db.router.db_for_read", return_value="default"):
            cohort.insert_users_list_by_uuid(
                items=[str(person.uuid)],
                team_id=self.team.id,
            )

        cohort.refresh_from_db()
        member_ids = list_cohort_member_ids(team_id=self.team.id, cohort_id=cohort.pk)
        assert len(member_ids) == 1
        assert str(_require_person_by_id(self.team.id, member_ids[0]).uuid) == str(person.uuid)

    @override_settings(DEBUG=False)
    def test_insert_re_raises_soft_time_limit_exceeded(self):
        # A Celery soft-time-limit interruption must propagate so the task's time limit
        # bounds the run. The broad except must not swallow it (DEBUG=False forces the
        # production path where everything else is swallowed). The finally still finalizes
        # cohort state before it propagates, recording the timeout as a failed
        # calculation — not a successful one.
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        cohort.is_calculating = True
        cohort.save(update_fields=["is_calculating"])

        def _raise_timeout(batch_index: int, batch_size: int) -> list[str]:
            raise SoftTimeLimitExceeded()

        iterator = FunctionBatchIterator(_raise_timeout, batch_size=10, max_items=10)

        with self.assertRaises(SoftTimeLimitExceeded):
            cohort._insert_users_list_with_batching(iterator, team_id=self.team.id)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        self.assertIsNotNone(cohort.last_error_at)
        self.assertIsNone(cohort.last_calculation)

    @parameterized.expand(
        [
            # operator, filter_value, excluded_ages, included_ages
            ["between", [18, 65], [15, 70], [25, 35, 18, 65]],
            ["not_between", [18, 65], [25, 18, 65], [15, 70]],
            ["min", 18, [15], [18, 25]],
            ["max", 65, [70], [25, 65]],
        ]
    )
    def test_calculating_cohort_with_numeric_property_operators(
        self, operator, filter_value, excluded_ages, included_ages
    ):
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="age", property_type=PropertyType.Numeric
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "age", "value": filter_value, "operator": operator, "type": "person"}]}],
            name="my_cohort",
        )

        for age in excluded_ages:
            create_person(
                distinct_ids=[str(uuid.uuid4())],
                team_id=self.team.pk,
                properties={"age": age},
            )

        expected_people = []
        for age in included_ages:
            person = create_person(
                distinct_ids=[str(uuid.uuid4())],
                team_id=self.team.pk,
                properties={"age": age},
            )
            expected_people.append(person)

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

        self.assertCountEqual(uuids, [p.uuid for p in expected_people])

    def test_get_static_cohort_size(self):
        """Test that get_static_cohort_size works with db_constraint=False on the person foreign key."""
        from products.cohorts.backend.models.util import get_static_cohort_size

        # Create persons
        person1 = create_person(team=self.team, distinct_ids=["person1"])
        person2 = create_person(team=self.team, distinct_ids=["person2"])
        person3 = create_person(team=self.team, distinct_ids=["person3"])

        # Create a static cohort
        cohort = Cohort.objects.create(team=self.team, name="Test Static Cohort", is_static=True)

        # Add persons to cohort
        add_cohort_members(cohort, [person1, person2, person3])

        # Test that get_static_cohort_size returns the correct count
        size = get_static_cohort_size(cohort_id=cohort.id, team_id=self.team.id)

        # This should return 3, not a CombinedExpression
        assert isinstance(size, int), f"Expected int, got {type(size)}: {size}"
        assert size == 3, f"Expected 3 persons in cohort, got {size}"

        # Cross-team CohortPeople rows are counted: get_static_cohort_size scopes by
        # cohort_id (gated by an upfront `Cohort.team_id == team_id` ownership check
        # in count_cohort_members), not by person.team_id. The previous join through
        # posthog_person was a hot per-PK lookup on the write replica that we
        # dropped for IOPS reasons — production cannot reach this state via the
        # supported APIs, and a cross-team add like the one below is what would have
        # had to break for a count discrepancy to surface in real traffic.
        team2 = Team.objects.create(organization=self.organization)
        person4 = create_person(team=team2, distinct_ids=["person4"])
        add_cohort_members(cohort, [person4])

        size = get_static_cohort_size(cohort_id=cohort.id, team_id=self.team.id)
        assert size == 4, f"Expected 4 cohort rows after cross-team add, got {size}"

    @pytest.mark.ee
    def test_calculate_people_ch_clears_realtime_type_when_exceeding_threshold(self):
        from unittest.mock import patch

        from products.cohorts.backend.models.cohort import REALTIME_COHORT_MAX_PERSON_COUNT

        # Create a realtime cohort
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="large cohort",
            cohort_type="realtime",
        )

        # Mock recalculate_cohortpeople to return a count exceeding the threshold
        with patch("products.cohorts.backend.models.util.recalculate_cohortpeople") as mock_recalc:
            mock_recalc.return_value = REALTIME_COHORT_MAX_PERSON_COUNT + 1

            cohort.calculate_people_ch(pending_version=1)

            # Verify cohort_type was cleared
            cohort.refresh_from_db()
            self.assertIsNone(cohort.cohort_type)
            self.assertEqual(cohort.count, REALTIME_COHORT_MAX_PERSON_COUNT + 1)

    @pytest.mark.ee
    def test_calculate_people_ch_keeps_realtime_type_when_at_threshold(self):
        from unittest.mock import patch

        from products.cohorts.backend.models.cohort import REALTIME_COHORT_MAX_PERSON_COUNT

        # Create a realtime cohort
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="at threshold cohort",
            cohort_type="realtime",
        )

        # Mock recalculate_cohortpeople to return exactly the threshold count
        with patch("products.cohorts.backend.models.util.recalculate_cohortpeople") as mock_recalc:
            mock_recalc.return_value = REALTIME_COHORT_MAX_PERSON_COUNT

            cohort.calculate_people_ch(pending_version=1)

            # Verify cohort_type was NOT cleared (at threshold is still OK)
            cohort.refresh_from_db()
            self.assertEqual(cohort.cohort_type, "realtime")
            self.assertEqual(cohort.count, REALTIME_COHORT_MAX_PERSON_COUNT)

    @parameterized.expand(
        [
            ("_safe_reset_calculating_state", "DB connection lost"),
            ("save", "DB error"),
        ]
    )
    @pytest.mark.ee
    def test_calculate_people_ch_updates_version_even_when_finally_raises(self, method_name, error_message):
        from unittest.mock import patch

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="version resilience cohort",
        )

        with patch("products.cohorts.backend.models.util.recalculate_cohortpeople") as mock_recalc:
            mock_recalc.return_value = 42

            with patch.object(Cohort, method_name, side_effect=Exception(error_message)):
                with pytest.raises(Exception, match=error_message):
                    cohort.calculate_people_ch(pending_version=1)

        # Version and count should be updated despite the finally block raising
        cohort.refresh_from_db()
        self.assertEqual(cohort.version, 1)
        self.assertEqual(cohort.count, 42)


_PERSON_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [{"type": "AND", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
    }
}

_BEHAVIORAL_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {"type": "behavioral", "value": "performed_event", "event_type": "events", "key": "$pageview"}
                ],
            }
        ],
    }
}

_MIXED_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [
            {"type": "AND", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]},
            {
                "type": "AND",
                "values": [
                    {"type": "behavioral", "value": "performed_event", "event_type": "events", "key": "$pageview"}
                ],
            },
        ],
    }
}

_COHORT_REF_FILTERS = {
    "properties": {
        "type": "AND",
        "values": [{"type": "AND", "values": [{"key": "id", "value": 1, "type": "cohort"}]}],
    }
}

_FIXED_TS = datetime(2026, 1, 1, tzinfo=UTC)


class TestCohortIsFlagCompatible(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand(
        [
            # (label, cohort_type, filters, person_ts, events_ts, expected)
            # Non-realtime cohort types are never flag-compatible
            ("static_never_compatible", CohortType.STATIC, _PERSON_FILTERS, _FIXED_TS, _FIXED_TS, False),
            ("behavioral_type_never_compatible", CohortType.BEHAVIORAL, _PERSON_FILTERS, _FIXED_TS, _FIXED_TS, False),
            (
                "person_property_type_never_compatible",
                CohortType.PERSON_PROPERTY,
                _PERSON_FILTERS,
                _FIXED_TS,
                None,
                False,
            ),
            # Realtime + person filters: gate on person timestamp
            ("realtime_person_no_ts", CohortType.REALTIME, _PERSON_FILTERS, None, None, False),
            ("realtime_person_only_person_ts", CohortType.REALTIME, _PERSON_FILTERS, _FIXED_TS, None, True),
            ("realtime_person_only_events_ts", CohortType.REALTIME, _PERSON_FILTERS, None, _FIXED_TS, False),
            ("realtime_person_both_ts", CohortType.REALTIME, _PERSON_FILTERS, _FIXED_TS, _FIXED_TS, True),
            # Realtime + behavioral filters: gate on events timestamp
            ("realtime_behavioral_no_ts", CohortType.REALTIME, _BEHAVIORAL_FILTERS, None, None, False),
            ("realtime_behavioral_only_person_ts", CohortType.REALTIME, _BEHAVIORAL_FILTERS, _FIXED_TS, None, False),
            ("realtime_behavioral_only_events_ts", CohortType.REALTIME, _BEHAVIORAL_FILTERS, None, _FIXED_TS, True),
            ("realtime_behavioral_both_ts", CohortType.REALTIME, _BEHAVIORAL_FILTERS, _FIXED_TS, _FIXED_TS, True),
            # Realtime + mixed filters: require both timestamps
            ("realtime_mixed_no_ts", CohortType.REALTIME, _MIXED_FILTERS, None, None, False),
            ("realtime_mixed_only_person_ts", CohortType.REALTIME, _MIXED_FILTERS, _FIXED_TS, None, False),
            ("realtime_mixed_only_events_ts", CohortType.REALTIME, _MIXED_FILTERS, None, _FIXED_TS, False),
            ("realtime_mixed_both_ts", CohortType.REALTIME, _MIXED_FILTERS, _FIXED_TS, _FIXED_TS, True),
            # Realtime + no recognized filter types: never compatible, regardless of timestamps
            ("realtime_empty_filters_no_ts", CohortType.REALTIME, {}, None, None, False),
            ("realtime_empty_filters_with_ts", CohortType.REALTIME, {}, _FIXED_TS, _FIXED_TS, False),
            ("realtime_cohort_ref_with_ts", CohortType.REALTIME, _COHORT_REF_FILTERS, _FIXED_TS, _FIXED_TS, False),
        ]
    )
    def test_is_flag_compatible(self, _label, cohort_type, filters, person_ts, events_ts, expected):
        cohort = Cohort.objects.create(
            team=self.team,
            filters=filters,
            cohort_type=cohort_type,
            last_backfill_person_properties_at=person_ts,
            last_backfill_events_at=events_ts,
        )
        self.assertEqual(cohort.is_flag_compatible, expected)
