from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_flag_evaluations,
    _create_person,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery

from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig


class TestHogQLCohortQuery(ClickhouseTestMixin, APIBaseTest):
    """Tests for HogQLCohortQuery, particularly the optimization for multiple person property filters."""

    def test_dynamic_cohort_id_is_not_injectable(self) -> None:
        # A static/dynamic-cohort property whose value is an arbitrary string (e.g. smuggled through
        # the unvalidated legacy `groups` field) must be rejected, not interpolated into the query.
        for cohort_type in ("dynamic-cohort", "static-cohort"):
            cohort = Cohort.objects.create(
                team=self.team,
                name=f"malicious-{cohort_type}",
                groups=[{"properties": [{"key": "id", "type": cohort_type, "value": "0 OR 1=1"}]}],
            )
            with self.assertRaises(ValueError):
                HogQLCohortQuery(cohort=cohort).get_query()

    def test_performed_event_multiple_without_time_range_raises_validation_error(self) -> None:
        # Recalculation maps a DRF ValidationError to the VALIDATION_ERROR code, not UNKNOWN.
        cohort = Cohort.objects.create(
            team=self.team,
            name="no time range",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "type": "behavioral",
                                    "value": "performed_event_multiple",
                                    "event_type": "events",
                                    "operator": "gte",
                                    "operator_value": 2,
                                    "conditionHash": "abc123",
                                    "bytecode": ["_H", 1, 29],
                                }
                            ],
                        }
                    ],
                }
            },
        )
        with self.assertRaisesMessage(ValidationError, "needs either a valid time range or an explicit_datetime"):
            HogQLCohortQuery(cohort=cohort).get_query()

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_multiple_person_properties_optimization(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that multiple person property filters in an AND group are combined into a single query.

        This optimization prevents generating N separate queries with N-1 INTERSECT DISTINCT operations,
        which is extremely inefficient for cohorts with many person property filters.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "is_set",
                            "operator": "is_set",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@hotmail",
                            "negation": False,
                            "operator": "icontains",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@yahoo",
                            "negation": False,
                            "operator": "not_icontains",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Multiple Filters Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # If the optimization worked, there should be no INTERSECT in the query
        self.assertNotIn("INTERSECT DISTINCT", query_str)
        self.assertIn(
            "and(isNotNull(persons.properties___email), ifNull(ilike(toString(persons.properties___email), %(hogql_val_8)s), 0), ifNull(notILike(toString(persons.properties___email), %(hogql_val_9)s), 1))",
            query_str,
        )

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_optimization_disabled_when_feature_flag_off(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that the optimization is disabled when the feature flag is off.

        When the feature flag is disabled, multiple person properties should be processed
        separately and combined with INTERSECT DISTINCT instead of a single query.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "is_set",
                            "operator": "is_set",
                        },
                        {
                            "key": "name",
                            "type": "person",
                            "value": "John",
                            "negation": False,
                            "operator": "icontains",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Feature Flag Off Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # With the feature flag off, should use INTERSECT DISTINCT
        self.assertIn("INTERSECT DISTINCT", query_str)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_optimization_skipped_for_mixed_property_types(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that the optimization is skipped when mixing person and behavioral properties.

        The optimization only applies to pure person property filters. When behavioral
        properties are mixed in, each property should be processed separately.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "is_set",
                            "operator": "is_set",
                        },
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": False,
                            "event_type": "events",
                            "time_value": 30,
                            "time_interval": "day",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Mixed Properties Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Should use INTERSECT DISTINCT because properties are mixed
        self.assertIn("INTERSECT DISTINCT", query_str)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_optimization_skipped_for_properties_with_negation(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that the optimization is skipped when any property has negation.

        The optimization only applies when all person properties are positive (not negated).
        If any property is negated, each property should be processed separately.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "is_set",
                            "operator": "is_set",
                        },
                        {
                            "key": "name",
                            "type": "person",
                            "value": "Spam",
                            "negation": True,
                            "operator": "icontains",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Negation Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Should use EXCEPT because one property is negated
        self.assertIn("EXCEPT", query_str)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_multiple_person_properties_or_optimization(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that multiple person property filters in an OR group are combined into a single query.

        This optimization prevents generating N separate queries with N-1 UNION DISTINCT operations,
        which causes ClickHouse to materialize IN subqueries during query planning, leading to
        OOM and timeout issues for large person tables.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "internal_user",
                            "type": "person",
                            "negation": False,
                            "value": ["yes", "true"],
                            "operator": "exact",
                        },
                        {
                            "key": "engineering_team",
                            "type": "person",
                            "value": True,
                            "negation": False,
                            "operator": "exact",
                        },
                        {
                            "key": "beta_tester",
                            "type": "person",
                            "value": True,
                            "negation": False,
                            "operator": "exact",
                        },
                        {
                            "key": "alpha_tester",
                            "type": "person",
                            "value": True,
                            "negation": False,
                            "operator": "exact",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test OR Optimization Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # If the optimization worked, there should be no UNION DISTINCT in the query
        self.assertNotIn("UNION DISTINCT", query_str)
        # Should have OR logic in the WHERE clause
        self.assertIn("or(", query_str)

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_or_optimization_disabled_when_feature_flag_off(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that the OR optimization is disabled when the feature flag is off.

        When the feature flag is disabled, multiple person properties in OR should be processed
        separately and combined with UNION DISTINCT instead of a single query.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "@gmail.com",
                            "operator": "icontains",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@yahoo.com",
                            "negation": False,
                            "operator": "icontains",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test OR Feature Flag Off Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # With the feature flag off, should use UNION DISTINCT
        self.assertIn("UNION DISTINCT", query_str)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_or_optimization_skipped_for_mixed_property_types(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that the OR optimization is skipped when mixing person and behavioral properties.

        The optimization only applies to pure person property filters. When behavioral
        properties are mixed in, each property should be processed separately.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "@gmail.com",
                            "operator": "icontains",
                        },
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": False,
                            "event_type": "events",
                            "time_value": 30,
                            "time_interval": "day",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test OR Mixed Properties Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Should use UNION DISTINCT because properties are mixed
        self.assertIn("UNION DISTINCT", query_str)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_or_optimization_skipped_for_properties_with_negation(self, mock_feature_enabled: MagicMock) -> None:
        """
        Test that the OR optimization is skipped when properties have negation.

        The optimization only applies when all person properties are positive (not negated).
        If properties are negated, each property should be processed separately using UNION DISTINCT.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "negation": False,
                            "value": "is_set",
                            "operator": "is_set",
                        },
                    ],
                },
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "name",
                            "type": "person",
                            "negation": True,
                            "value": "Spam",
                            "operator": "icontains",
                        },
                        {
                            "key": "name",
                            "type": "person",
                            "value": "Bot",
                            "negation": True,
                            "operator": "icontains",
                        },
                    ],
                },
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test OR Negation Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # OR with all negated properties doesn't get optimized and uses INTERSECT DISTINCT
        # (because all_children_negated = True)
        self.assertIn("INTERSECT DISTINCT", query_str)
        # Should not use the OR optimization (which would create a single query with OR logic)
        self.assertNotIn("or(", query_str)

    def test_person_metadata_created_at_cohort(self) -> None:
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "created_at",
                            "type": "person_metadata",
                            "value": "2024-01-01",
                            "operator": "is_date_after",
                        }
                    ],
                }
            ],
        }
        cohort = Cohort.objects.create(
            team=self.team, name="created after 2024", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        self.assertIn("created_at", query_str)
        # Should compare against the persons table column, not the properties JSON blob
        self.assertNotIn("properties___created_at", query_str)

    def test_person_metadata_cohort_membership_end_to_end(self) -> None:
        # Persons need a deterministic created_at in BOTH Postgres and ClickHouse.
        # _create_person with immediate=True under a frozen clock writes both stores; we also
        # pass created_at explicitly so the assertion stays valid even if Postgres stops
        # using auto_now_add or default=timezone.now in a future migration.
        utc = ZoneInfo("UTC")
        old_dt = datetime(2023, 1, 1, tzinfo=utc)
        new_dt = datetime(2025, 1, 1, tzinfo=utc)
        with time_machine.travel(old_dt, tick=False):
            old_person = _create_person(
                team=self.team,
                distinct_ids=["old"],
                properties={"name": "old user"},
                created_at=old_dt,
                immediate=True,
            )
        with time_machine.travel(new_dt, tick=False):
            new_person = _create_person(
                team=self.team,
                distinct_ids=["new"],
                properties={"name": "new user"},
                created_at=new_dt,
                immediate=True,
            )
        flush_persons_and_events()

        cohort = cast(
            Cohort,
            Cohort.objects.create(
                team=self.team,
                name="created after 2024",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "created_at",
                                        "type": "person_metadata",
                                        "value": "2024-06-01",
                                        "operator": "is_date_after",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
        )
        cohort.calculate_people_ch(pending_version=0)

        rows = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s "
            "GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0",
            {"cohort_id": cohort.pk, "team_id": self.team.pk},
        )
        member_ids = {str(row[0]) for row in rows}
        self.assertIn(str(new_person.uuid), member_ids)
        self.assertNotIn(str(old_person.uuid), member_ids)

    @parameterized.expand(
        [
            ("email", "starts_with", "first", "first"),
            ("email", "not_starts_with", "first", "second"),
            ("email", "ends_with", ".org", "second"),
            ("email", "not_ends_with", ".org", "first"),
            ("app_version", "semver_eq", "1.2.4", "first"),
            ("app_version", "semver_neq", "1.2.4", "second"),
            ("app_version", "semver_gt", "1.2.4", "second"),
            ("app_version", "semver_gte", "2.0.0", "second"),
            ("app_version", "semver_lt", "2.0.0", "first"),
            ("app_version", "semver_lte", "1.2.4", "first"),
            ("app_version", "semver_tilde", "1.2.3", "first"),
            ("app_version", "semver_caret", "1.2.3", "first"),
            ("app_version", "semver_wildcard", "2.*", "second"),
            ("birth_date", "is_set", None, "first"),
            ("birth_date", "is_not_set", None, "second"),
        ]
    )
    def test_person_property_operators_calculate_cohort_membership(
        self, key: str, operator: str, value: str | None, expected_member: str
    ) -> None:
        PropertyDefinition.objects.create(
            team=self.team,
            name="birth_date",
            property_type=PropertyType.Datetime,
            type=PropertyDefinition.Type.PERSON,
        )
        members = {
            "first": _create_person(
                team=self.team,
                distinct_ids=["first"],
                properties={"email": "first@example.com", "app_version": "1.2.4", "birth_date": "2000-01-01"},
                immediate=True,
            ),
            "second": _create_person(
                team=self.team,
                distinct_ids=["second"],
                properties={"email": "second@example.org", "app_version": "2.0.0"},
                immediate=True,
            ),
        }
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name=f"{operator} cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": key, "type": "person", "operator": operator, "value": value}],
                        }
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        self.assertEqual(self._cohort_member_ids(cohort, 0), {str(members[expected_member].uuid)})

    def _cohort_member_ids(self, cohort: Cohort, version: int) -> set[str]:
        rows = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s "
            "AND version = %(version)s GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0",
            {"cohort_id": cohort.pk, "team_id": self.team.pk, "version": version},
        )
        return {str(row[0]) for row in rows}

    def test_performed_flag_call_criterion_reads_flag_evaluations_when_the_rewrite_is_on(self) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization,
            defaults={"flag_evaluations_mode": FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY},
        )
        caller = _create_person(team=self.team, distinct_ids=["caller"], immediate=True)
        other_caller = _create_person(team=self.team, distinct_ids=["other-caller"], immediate=True)
        flush_persons_and_events()
        _create_flag_evaluations(self.team.pk, "probe-flag", distinct_id="caller", person_id=caller.uuid)
        _create_flag_evaluations(self.team.pk, "other-flag", distinct_id="other-caller", person_id=other_caller.uuid)
        cohort = Cohort.objects.create(
            team=self.team,
            name="called probe-flag",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$feature_flag_called",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_value": 30,
                                    "time_interval": "day",
                                    "event_filters": [
                                        {
                                            "key": "$feature_flag",
                                            "type": "event",
                                            "value": "probe-flag",
                                            "operator": "exact",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        with patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda key, *args, **kwargs: key == "hogql-flag-calls-from-flag-evaluations",
        ):
            cohort.calculate_people_ch(pending_version=0)

        self.assertEqual(self._cohort_member_ids(cohort, 0), {str(caller.uuid)})

    def test_filter_test_accounts_excludes_person_matches_and_tracks_team_settings(self) -> None:
        internal = _create_person(
            team=self.team,
            distinct_ids=["internal"],
            properties={"email": "employee@posthog.com", "plan": "paid"},
            immediate=True,
        )
        external = _create_person(
            team=self.team,
            distinct_ids=["external"],
            properties={"email": "customer@example.com", "plan": "paid"},
            immediate=True,
        )
        flush_persons_and_events()

        self.team.test_account_filters = [
            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()

        cohort = cast(
            Cohort,
            Cohort.objects.create(
                team=self.team,
                name="paid users",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "plan", "type": "person", "value": "paid", "operator": "exact"}],
                            }
                        ],
                    },
                    "filterTestAccounts": True,
                },
            ),
        )

        cohort.calculate_people_ch(pending_version=0)
        members = self._cohort_member_ids(cohort, version=0)
        self.assertIn(str(external.uuid), members)
        self.assertNotIn(str(internal.uuid), members)

        # The team's filters are read at calculation time, not copied into the cohort, so clearing
        # them re-includes the internal person on the next recalculation.
        self.team.test_account_filters = []
        self.team.save()
        cohort.calculate_people_ch(pending_version=1)
        members = self._cohort_member_ids(cohort, version=1)
        self.assertIn(str(external.uuid), members)
        self.assertIn(str(internal.uuid), members)

    def test_person_metadata_cohort_membership_negated_end_to_end(self) -> None:
        # Mirror of the is_date_after test with is_date_before, so membership inverts: the OLD
        # person should be in the cohort and the NEW person should not. Covers the operator whose
        # missing-value default differs in the Rust matcher (the silent-grant class).
        utc = ZoneInfo("UTC")
        old_dt = datetime(2023, 1, 1, tzinfo=utc)
        new_dt = datetime(2025, 1, 1, tzinfo=utc)
        with time_machine.travel(old_dt, tick=False):
            old_person = _create_person(
                team=self.team,
                distinct_ids=["old_neg"],
                properties={"name": "old user"},
                created_at=old_dt,
                immediate=True,
            )
        with time_machine.travel(new_dt, tick=False):
            new_person = _create_person(
                team=self.team,
                distinct_ids=["new_neg"],
                properties={"name": "new user"},
                created_at=new_dt,
                immediate=True,
            )
        flush_persons_and_events()

        cohort = cast(
            Cohort,
            Cohort.objects.create(
                team=self.team,
                name="created before 2024",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "created_at",
                                        "type": "person_metadata",
                                        "value": "2024-06-01",
                                        "operator": "is_date_before",
                                    }
                                ],
                            }
                        ],
                    }
                },
            ),
        )
        cohort.calculate_people_ch(pending_version=0)

        rows = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s "
            "GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0",
            {"cohort_id": cohort.pk, "team_id": self.team.pk},
        )
        member_ids = {str(row[0]) for row in rows}
        self.assertIn(str(old_person.uuid), member_ids)
        self.assertNotIn(str(new_person.uuid), member_ids)

    def test_static_cohort_condition_rejects_cross_project_cohort(self) -> None:
        from posthog.models.organization import Organization

        _, _, other_team = Organization.objects.bootstrap(self.user, name="other org")
        other_static_cohort = Cohort.objects.create(
            team=other_team, name="Other Static Cohort", is_static=True, is_calculating=False
        )

        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {"key": "id", "type": "static-cohort", "value": other_static_cohort.id, "negation": False}
                    ],
                }
            ],
        }
        cohort = Cohort.objects.create(
            team=self.team, name="References Cross-Project Cohort", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLCohortQuery(cohort=cohort)
        with self.assertRaises(Cohort.DoesNotExist):
            hogql_query.query_str("clickhouse")
