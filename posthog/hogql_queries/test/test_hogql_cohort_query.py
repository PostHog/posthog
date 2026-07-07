import datetime as dt
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.constants import PropertyOperatorType
from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery, HogQLRealtimeCohortQuery
from posthog.models.property import Property, PropertyGroup

from products.cohorts.backend.models.cohort import Cohort

# Local single-node mirror of the production precalculated_person_properties table (which is
# sharded/distributed and absent from the test ClickHouse schema). Created per execution test.
_PRECALCULATED_PERSON_PROPERTIES_TEST_DDL = """
CREATE TABLE IF NOT EXISTS precalculated_person_properties (
    team_id Int64, distinct_id String, person_id UUID, condition String,
    matches Bool, source String, _timestamp DateTime64(6), _offset UInt64
) ENGINE = ReplacingMergeTree(_timestamp) ORDER BY (team_id, condition, distinct_id)
"""


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

    def test_negative_only_behavioral_cohort_membership_end_to_end(self) -> None:
        now = dt.datetime(2025, 1, 15, tzinfo=ZoneInfo("UTC"))
        with freeze_time(now):
            purchased_person = _create_person(
                team=self.team,
                distinct_ids=["purchased"],
                properties={"email": "purchased@example.com"},
                immediate=True,
            )
            not_purchased_person = _create_person(
                team=self.team,
                distinct_ids=["not_purchased"],
                properties={"email": "not-purchased@example.com"},
                immediate=True,
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id="purchased",
                timestamp=now,
            )
            flush_persons_and_events()

            cohort = Cohort.objects.create(
                team=self.team,
                name="Did not purchase",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "purchase",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "negation": True,
                                        "event_type": "events",
                                        "time_value": 30,
                                        "time_interval": "day",
                                    }
                                ],
                            }
                        ],
                    }
                },
            )
            cohort.calculate_people_ch(pending_version=0)

        rows = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s "
            "GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0",
            {"cohort_id": cohort.pk, "team_id": self.team.pk},
        )
        member_ids = {str(row[0]) for row in rows}
        self.assertIn(str(not_purchased_person.uuid), member_ids)
        self.assertNotIn(str(purchased_person.uuid), member_ids)

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
        # _create_person with immediate=True under freeze_time writes both stores; we also
        # pass created_at explicitly so the assertion stays valid even if Postgres stops
        # using auto_now_add or default=timezone.now in a future migration.
        utc = ZoneInfo("UTC")
        old_dt = datetime(2023, 1, 1, tzinfo=utc)
        new_dt = datetime(2025, 1, 1, tzinfo=utc)
        with freeze_time(old_dt):
            old_person = _create_person(
                team=self.team,
                distinct_ids=["old"],
                properties={"name": "old user"},
                created_at=old_dt,
                immediate=True,
            )
        with freeze_time(new_dt):
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

        from posthog.clickhouse.client.execute import sync_execute

        rows = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s "
            "GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0",
            {"cohort_id": cohort.pk, "team_id": self.team.pk},
        )
        member_ids = {str(row[0]) for row in rows}
        self.assertIn(str(new_person.uuid), member_ids)
        self.assertNotIn(str(old_person.uuid), member_ids)

    def test_person_metadata_cohort_membership_negated_end_to_end(self) -> None:
        # Mirror of the is_date_after test with is_date_before, so membership inverts: the OLD
        # person should be in the cohort and the NEW person should not. Covers the operator whose
        # missing-value default differs in the Rust matcher (the silent-grant class).
        utc = ZoneInfo("UTC")
        old_dt = datetime(2023, 1, 1, tzinfo=utc)
        new_dt = datetime(2025, 1, 1, tzinfo=utc)
        with freeze_time(old_dt):
            old_person = _create_person(
                team=self.team,
                distinct_ids=["old_neg"],
                properties={"name": "old user"},
                created_at=old_dt,
                immediate=True,
            )
        with freeze_time(new_dt):
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

        from posthog.clickhouse.client.execute import sync_execute

        rows = sync_execute(
            "SELECT person_id FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s "
            "GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0",
            {"cohort_id": cohort.pk, "team_id": self.team.pk},
        )
        member_ids = {str(row[0]) for row in rows}
        self.assertIn(str(old_person.uuid), member_ids)
        self.assertNotIn(str(new_person.uuid), member_ids)

    def test_person_metadata_realtime_cohort_raises_error(self) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="created after 2024 realtime",
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
                                    "conditionHash": "test_pm_hash",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        with self.assertRaises(ValueError) as ctx:
            hogql_query.query_str("clickhouse")
        self.assertIn("person_metadata", str(ctx.exception))

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


class TestHogQLRealtimeCohortQuery(ClickhouseTestMixin, APIBaseTest):
    """Tests for HogQLRealtimeCohortQuery which uses precalculated_events for behavioral filters."""

    def test_person_property_query(self) -> None:
        """
        Test that person property filters work correctly in realtime cohorts.
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
                            "value": "@posthog.com",
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "test123abc456",
                            "bytecode": ["_H", 1, 32, "email", 32, "@posthog.com", 2, "icontains", 2],
                        }
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Realtime Person Property", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Should query precalculated_person_properties table for person properties
        self.assertIn("precalculated_person_properties", query_str)
        # Should have condition hash filter
        self.assertIn("condition", query_str)

    def test_behavioral_performed_event_pageview(self) -> None:
        """
        Test that a simple behavioral performed_event filter works with conditionHash.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": False,
                            "event_type": "events",
                            "time_value": 7,
                            "time_interval": "day",
                            "conditionHash": "abc123def456",
                        }
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Behavioral Pageview", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        query_str = hogql_query.query_str("clickhouse")

        # Should query precalculated_events table
        self.assertIn("precalculated_events", query_str)
        # Should have condition field (conditionHash is parameterized)
        self.assertIn("precalculated_events.condition", query_str)
        # Should use person_id directly from precalculated_events
        self.assertIn("person_id", query_str)
        # Should have date filtering with toDate
        self.assertIn("toDate", query_str)

    def test_cohort_membership_in_cohort_direct(self) -> None:
        """
        Test that get_dynamic_cohort_condition generates correct query for cohort membership.
        """
        from posthog.models.property import Property

        # Create a target cohort
        target_cohort = Cohort.objects.create(
            team=self.team, name="Target Cohort", filters={"properties": {"type": "AND", "values": []}}
        )

        # Create a simple cohort for the query object
        cohort = Cohort.objects.create(
            team=self.team, name="Test Cohort", filters={"properties": {"type": "AND", "values": []}}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        # Create a dynamic-cohort property (this is what unwrap_cohort would create)
        prop = Property(type="dynamic-cohort", key="id", value=target_cohort.id, negation=False)

        # Call get_dynamic_cohort_condition directly
        query_ast = hogql_query.get_dynamic_cohort_condition(prop)

        # Print the AST to string
        from posthog.hogql.printer import prepare_and_print_ast

        query_str = prepare_and_print_ast(query_ast, hogql_query.hogql_context, "clickhouse", pretty=True)[0]

        # Should query cohort_membership table
        self.assertIn("cohort_membership", query_str)
        # Should have cohort_id filter
        self.assertIn("cohort_membership.cohort_id", query_str)
        # Should check status field and use argMax for latest status
        self.assertIn("cohort_membership.status", query_str)
        self.assertIn("argmax", query_str.lower())
        # Should filter by person_id and use HAVING clause for status check
        self.assertIn("person_id", query_str.lower())
        self.assertIn("having", query_str.lower())

    def test_cohort_membership_not_in_cohort_direct(self) -> None:
        """
        Test that negated cohort membership uses EXCEPT to exclude cohort members.
        """
        from posthog.hogql.printer import prepare_and_print_ast

        from posthog.models.property import Property

        # Create a target cohort
        target_cohort = Cohort.objects.create(
            team=self.team, name="Target Cohort", filters={"properties": {"type": "AND", "values": []}}
        )

        # Create a simple cohort for the query object
        cohort = Cohort.objects.create(
            team=self.team, name="Test Cohort", filters={"properties": {"type": "AND", "values": []}}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        # Create a negated dynamic-cohort property
        prop = Property(type="dynamic-cohort", key="id", value=target_cohort.id, negation=True)

        # When negation=True, the property is handled through build_conditions with EXCEPT
        # We need to test through _get_condition_for_property
        query_ast = hogql_query._get_condition_for_property(prop)

        # Print the AST to string
        query_str = prepare_and_print_ast(query_ast, hogql_query.hogql_context, "clickhouse", pretty=True)[0]

        # Should still query cohort_membership table
        self.assertIn("cohort_membership", query_str)
        # Should have cohort_id filter
        self.assertIn("cohort_membership.cohort_id", query_str)

    def test_behavioral_performed_event_multiple(self) -> None:
        """
        Test that performed_event_multiple queries precalculated_events with count aggregation.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event_multiple",
                            "negation": False,
                            "operator": "gte",
                            "event_type": "events",
                            "operator_value": 5,
                            "time_value": 30,
                            "time_interval": "day",
                            "conditionHash": "xyz789abc123",
                        }
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Behavioral Multiple", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Should query precalculated_events
        self.assertIn("precalculated_events", query_str)
        # Should have count aggregation
        self.assertIn("count()", query_str)
        # Should have HAVING clause for count filtering
        self.assertIn("HAVING", query_str)
        # Should use person_id directly from precalculated_events
        self.assertIn("person_id", query_str)
        # Should group by person_id
        self.assertIn("GROUP BY", query_str)

    def test_behavioral_performed_event_with_date_range(self) -> None:
        """performed_event with explicit_datetime + explicit_datetime_to bounds both ends of the window."""
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": False,
                            "event_type": "events",
                            "explicit_datetime": "-30d",
                            "explicit_datetime_to": "-7d",
                            "conditionHash": "range_hash_1",
                        }
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Behavioral Range", filters={"properties": cohort_filters}
        )
        query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse")

        self.assertIn("precalculated_events", query_str)
        # Both sides of the window should be emitted. HogQL prints `>=`/`<=` as
        # `greaterOrEquals(...)` / `lessOrEquals(...)` function calls for ClickHouse.
        self.assertEqual(query_str.count("toDate("), 2)
        self.assertIn("greaterOrEquals", query_str)
        self.assertIn("lessOrEquals", query_str)

    def test_behavioral_performed_event_multiple_with_date_range(self) -> None:
        """performed_event_multiple with a bounded window still aggregates counts."""
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event_multiple",
                            "negation": False,
                            "operator": "gte",
                            "event_type": "events",
                            "operator_value": 3,
                            "explicit_datetime": "-30d",
                            "explicit_datetime_to": "-7d",
                            "conditionHash": "range_hash_2",
                        }
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Behavioral Multiple Range", filters={"properties": cohort_filters}
        )
        query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse")

        self.assertIn("precalculated_events", query_str)
        self.assertIn("count()", query_str)
        self.assertIn("HAVING", query_str)
        self.assertEqual(query_str.count("toDate("), 2)

    def test_behavioral_performed_event_without_date_range_omits_upper_bound(self) -> None:
        """When only explicit_datetime is set, only the lower bound shows up."""
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "behavioral",
                            "value": "performed_event",
                            "negation": False,
                            "event_type": "events",
                            "explicit_datetime": "-30d",
                            "conditionHash": "range_hash_3",
                        }
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Behavioral Lower Bound", filters={"properties": cohort_filters}
        )
        query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse")

        self.assertEqual(query_str.count("toDate("), 1)
        self.assertNotIn("lessOrEquals", query_str)

    def test_static_cohort_raises_error(self) -> None:
        """
        Test that static cohort filters raise an error for realtime cohorts.
        Static cohorts are not supported in realtime calculation.
        """
        # First create a static cohort
        static_cohort = Cohort.objects.create(
            team=self.team, name="Static Cohort", is_static=True, is_calculating=False
        )

        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [{"key": "id", "type": "static-cohort", "value": static_cohort.id, "negation": False}],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Static Cohort Error", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        # Should raise ValueError when trying to generate query
        with self.assertRaises(ValueError) as context:
            hogql_query.query_str("clickhouse")

        self.assertIn("static cohort", str(context.exception).lower())

    def test_or_group_with_same_key_operator_merges(self) -> None:
        """
        Test that OR groups with same key and operator are merged with OR semantics.

        For example: email contains "@gmail.com" OR email contains "@yahoo.com"
        This should find users whose email contains ANY of these strings (at least one).

        Also tests that properties with different operators or keys are NOT merged.
        """
        cohort_filters = {
            "type": "OR",
            "values": [
                {
                    "type": "OR",
                    "values": [
                        # These 3 should merge (same key, operator, not negated)
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@gmail.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "a5c1c77ac5bfac89",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": ["@yahoo.com"],
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@yahoo.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "102924b91ae29fc8",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@live.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@live.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "e849069d7a368305",
                        },
                        # Different operator - should NOT merge
                        {
                            "key": "email",
                            "type": "person",
                            "value": "admin@company.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "admin@company.com",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                15,
                            ],
                            "negation": False,
                            "operator": "exact",
                            "conditionHash": "different_operator_hash",
                        },
                        # Different operator (negated version) - should NOT merge
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@hotmail.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@hotmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "not_icontains",
                            "conditionHash": "271b98d7d31ca2ce",
                        },
                        # Different key - should NOT merge
                        {
                            "key": "name",
                            "type": "person",
                            "value": "John",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%John%",
                                32,
                                "name",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "different_key_hash",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test OR Group Merge", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # All 6 conditions (3 mergeable + 3 non-mergeable) collapse into one scan with a
        # single IN clause and HAVING countIf >= 1 (OR semantics).
        self.assertIn("in(precalculated_person_properties.condition,", query_str.lower())
        self.assertNotIn("UNION DISTINCT", query_str)
        self.assertNotIn("INTERSECT DISTINCT", query_str)
        # OR threshold: at least one condition must match
        self.assertIn("countif(", query_str.lower())
        self.assertIn("greaterOrEquals", query_str)

    def test_or_group_with_nested_single_property_groups_merges(self) -> None:
        """
        Test that nested OR groups with single properties get merged.

        For example:
        OR:
          - Group 1: [email contains "@gmail.com"]
          - Group 2: [email contains "@yahoo.com"]
          - Group 3: [email contains "@live.com"]

        These should be unwrapped and merged into a single query.
        """
        cohort_filters = {
            "type": "OR",
            "values": [
                # Each of these is a separate OR group with a single property
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@gmail.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "nested1_gmail",
                        },
                    ],
                },
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@yahoo.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@yahoo.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "nested2_yahoo",
                        },
                    ],
                },
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@live.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@live.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "nested3_live",
                        },
                    ],
                },
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Nested OR Groups Merge", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # All 3 nested single-property groups should be unwrapped and merged
        # Should have exactly 1 IN clause for all 3 conditions
        in_clause_count = query_str.lower().count("in(precalculated_person_properties.condition,")
        self.assertEqual(in_clause_count, 1, "Should have exactly 1 IN clause for merged conditions")

        # Should have no single condition checks (all merged)
        single_condition_count = query_str.lower().count("equals(precalculated_person_properties.condition,")
        self.assertEqual(single_condition_count, 0, "Should have no single condition checks (all merged)")

        # Should NOT use UNION DISTINCT since all properties are merged
        self.assertNotIn("UNION DISTINCT", query_str)

    def test_and_group_with_same_key_operator_merges(self) -> None:
        """
        Test that AND groups with same key and operator are merged with AND semantics.

        For example: email contains "@gmail" AND email contains ".com"
        This should find users whose email contains ALL of these strings (all conditions must match).
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
                            "value": "@gmail",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash1_gmail",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": ".com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash2_dotcom",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "test",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%test%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash3_test",
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test AND Group Merge", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Should use IN clause to fetch all conditions at once
        self.assertIn("in(precalculated_person_properties.condition,", query_str.lower())
        # AND semantics: all 3 conditions must match. Pin the full predicate so the threshold
        # (3, not 1) is verified rather than a substring that any threshold would satisfy.
        self.assertIn("greaterorequals(countif(equals(latest_matches, 1)), 3)", query_str.lower())
        # Should NOT use UNION/INTERSECT DISTINCT since properties collapse into one scan
        self.assertNotIn("UNION DISTINCT", query_str)
        self.assertNotIn("INTERSECT DISTINCT", query_str)

    def test_sibling_single_property_groups_under_or_merge(self) -> None:
        """
        Test that sibling single-property groups under a top-level OR are merged together
        when they have the same key and operator, including already-merged groups.

        For example:
        OR:
          - AND: [email icontains @gmail.com, name icontains John]  # can't merge (different keys)
          - OR: [email icontains yahoo.com]  # single property
          - OR: [email icontains @protonmail.com, email icontains @live.com]  # already merged within group

        The last two groups should ALL be merged together (yahoo + protonmail + live = 3 hashes).
        """
        cohort_filters = {
            "type": "OR",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@gmail.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash1_gmail",
                        },
                        {
                            "key": "name",
                            "type": "person",
                            "value": "John",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%John%",
                                32,
                                "name",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash2_john",
                        },
                    ],
                },
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "yahoo.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%yahoo.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash3_yahoo",
                        },
                    ],
                },
                {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@protonmail.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@protonmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash4_protonmail",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@live.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@live.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "hash5_live",
                        },
                    ],
                },
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Sibling Single Property Groups Merge", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # The whole nested boolean is now evaluated in one scan's HAVING — no set operations.
        self.assertNotIn("UNION DISTINCT", query_str)
        self.assertNotIn("INTERSECT DISTINCT", query_str)
        self.assertIn("maxif(latest_matches", query_str.lower())

        # The 3 sibling email properties (yahoo + protonmail + live) still merge into one OR leaf,
        # so its IN tuple has exactly 3 values.
        tuple_pattern = r"tuple\(%\(hogql_val_\d+\)s,\s*%\(hogql_val_\d+\)s,\s*%\(hogql_val_\d+\)s\)"
        self.assertRegex(query_str, tuple_pattern, "merged email leaf should be a 3-value IN tuple")

    def test_properties_without_condition_hash_are_not_merged(self) -> None:
        """
        Test that properties without conditionHash are not merged and don't cause empty IN clauses.

        This tests the edge case where multiple properties have the same key and operator
        but none of them have conditionHash set. The validation should prevent creating
        a merged property with empty hashes.
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
                            "value": "@gmail.com",
                            "negation": False,
                            "operator": "icontains",
                            # Note: No conditionHash
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@yahoo.com",
                            "negation": False,
                            "operator": "icontains",
                            # Note: No conditionHash
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Properties Without Hash", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        # Should raise ValueError because realtime cohorts require conditionHash
        with self.assertRaises(ValueError) as context:
            hogql_query.query_str("clickhouse")

        self.assertIn("conditionhash", str(context.exception).lower())

    def test_merged_property_with_empty_hashes_raises_error(self) -> None:
        """
        Test that attempting to query a merged property with empty hashes raises a clear error.

        This tests the defensive validation in get_person_condition that prevents
        generating invalid SQL with empty IN clauses.
        """
        from posthog.models.property import Property

        cohort = Cohort.objects.create(
            team=self.team, name="Test Empty Hashes", filters={"properties": {"type": "AND", "values": []}}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        # Create a property with empty _merged_condition_hashes (simulating a bug)
        prop = Property(
            key="email",
            type="person",
            value="@gmail.com",
            negation=False,
            operator="icontains",
            conditionHash="test_hash",
        )
        # Simulate a bug where _merged_condition_hashes is set to empty list
        prop._merged_condition_hashes = []  # type: ignore[attr-defined]
        prop._is_or_group = True  # type: ignore[attr-defined]

        # Should raise ValueError about empty condition hashes
        with self.assertRaises(ValueError) as context:
            hogql_query.get_person_condition(prop)

        error_msg = str(context.exception).lower()
        self.assertIn("empty condition hashes", error_msg)
        self.assertIn("invalid sql", error_msg)

    def test_create_merged_property_with_empty_hashes_raises_error(self) -> None:
        """
        Test that _create_merged_property raises an error when called with empty unique_hashes.

        This ensures the method is defensive and validates its inputs.
        """
        from posthog.models.property import Property

        cohort = Cohort.objects.create(
            team=self.team, name="Test Create Merged Property", filters={"properties": {"type": "AND", "values": []}}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)

        template = Property(
            key="email",
            type="person",
            value="@gmail.com",
            negation=False,
            operator="icontains",
            conditionHash="test_hash",
        )

        # Should raise ValueError when unique_hashes is empty
        with self.assertRaises(ValueError) as context:
            hogql_query._create_merged_property(template, [], is_or_group=True)

        error_msg = str(context.exception).lower()
        self.assertIn("empty unique_hashes", error_msg)

    def test_duplicate_condition_hashes_deduplicated_correctly(self) -> None:
        """
        Test that duplicate condition hashes are deduplicated when merging properties.

        This tests the edge case where a user accidentally adds the same filter multiple times
        (e.g., "email contains @gmail.com" appears twice). The deduplication ensures that
        the count matches the distinct conditions in the GROUP BY query.
        """
        cohort_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        # Same condition hash appears 3 times (simulating accidental duplicates)
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@gmail.com",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "duplicate_hash_123",
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@gmail.com",  # Same filter again
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "duplicate_hash_123",  # Same hash
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@gmail.com",  # Same filter third time
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "%@gmail.com%",
                                32,
                                "email",
                                32,
                                "properties",
                                32,
                                "person",
                                1,
                                3,
                                2,
                                "toString",
                                1,
                                18,
                            ],
                            "negation": False,
                            "operator": "icontains",
                            "conditionHash": "duplicate_hash_123",  # Same hash again
                        },
                    ],
                }
            ],
        }

        cohort = Cohort.objects.create(
            team=self.team, name="Test Duplicate Hashes", filters={"properties": cohort_filters}
        )

        hogql_query = HogQLRealtimeCohortQuery(cohort=cohort)
        query_str = hogql_query.query_str("clickhouse")

        # Deduplicated to a single condition → cheaper one-pass query: `condition = hash`
        # equality, no IN clause and no cross-condition counting.
        self.assertIn("equals(precalculated_person_properties.condition,", query_str.lower())
        self.assertNotIn("in(precalculated_person_properties.condition,", query_str.lower())
        self.assertNotIn("countif", query_str.lower())

        # Should NOT use INTERSECT since all properties merged into one
        self.assertNotIn("INTERSECT DISTINCT", query_str)

    @parameterized.expand(
        [
            (
                # AND of 3 person properties with different keys → single scan, threshold = N (3)
                "cross_condition_and",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "negation": False,
                                    "operator": "icontains",
                                    "conditionHash": "hash_email_001",
                                },
                                {
                                    "key": "plan",
                                    "type": "person",
                                    "value": "enterprise",
                                    "negation": False,
                                    "operator": "exact",
                                    "conditionHash": "hash_plan_002",
                                },
                                {
                                    "key": "country",
                                    "type": "person",
                                    "value": "US",
                                    "negation": False,
                                    "operator": "exact",
                                    "conditionHash": "hash_country_003",
                                },
                            ],
                        }
                    ],
                },
                [
                    "in(precalculated_person_properties.condition,",
                    "greaterorequals(countif(equals(latest_matches, 1)), 3)",
                ],
                ["intersect distinct", "union distinct"],
            ),
            (
                # OR of 2 person properties with different keys → single scan, threshold = 1
                "cross_condition_or",
                {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "negation": False,
                                    "operator": "icontains",
                                    "conditionHash": "hash_email_or_001",
                                },
                                {
                                    "key": "plan",
                                    "type": "person",
                                    "value": "enterprise",
                                    "negation": False,
                                    "operator": "exact",
                                    "conditionHash": "hash_plan_or_002",
                                },
                            ],
                        }
                    ],
                },
                [
                    "in(precalculated_person_properties.condition,",
                    "greaterorequals(countif(equals(latest_matches, 1)), 1)",
                ],
                ["intersect distinct", "union distinct"],
            ),
            (
                # Mixed behavioral + person property → falls through to multi-subquery path
                "mixed_behavioral_and_person_falls_through",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "negation": False,
                                    "event_type": "events",
                                    "time_value": 7,
                                    "time_interval": "day",
                                    "conditionHash": "behavioral_hash_001",
                                },
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "negation": False,
                                    "operator": "icontains",
                                    "conditionHash": "person_hash_001",
                                },
                            ],
                        }
                    ],
                },
                ["intersect distinct", "precalculated_events", "precalculated_person_properties"],
                [],
            ),
            (
                # Single person property → cheaper one-pass query (no cross-condition counting)
                "single_property",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "negation": False,
                                    "operator": "icontains",
                                    "conditionHash": "hash_single_001",
                                },
                            ],
                        }
                    ],
                },
                ["equals(argmax(precalculated_person_properties.matches"],
                ["intersect distinct", "union distinct", "countif"],
            ),
            (
                # Negated person property → falls through (single-scan must NOT fire)
                "negated_person_falls_through",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "negation": False,
                                    "operator": "icontains",
                                    "conditionHash": "neg_keep_001",
                                },
                                {
                                    "key": "name",
                                    "type": "person",
                                    "value": "spam",
                                    "negation": True,
                                    "operator": "icontains",
                                    "conditionHash": "neg_drop_002",
                                },
                            ],
                        }
                    ],
                },
                ["precalculated_person_properties"],
                ["greaterorequals(countif(equals(latest_matches, 1))"],
            ),
            (
                # (X OR Y) AND (A OR B): nested OR groups under a top-level AND. The boolean-tree
                # single scan expresses this as `maxIf(...) = 1 AND maxIf(...) = 1`, NOT a flat
                # `>= 4` threshold (which would wrongly require all four).
                "nested_or_under_and_single_scan",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "OR",
                                    "values": [
                                        {
                                            "key": "email",
                                            "type": "person",
                                            "value": "@x.com",
                                            "negation": False,
                                            "operator": "icontains",
                                            "conditionHash": "nest_hx_001",
                                        },
                                        {
                                            "key": "email",
                                            "type": "person",
                                            "value": "@y.com",
                                            "negation": False,
                                            "operator": "icontains",
                                            "conditionHash": "nest_hy_002",
                                        },
                                    ],
                                },
                                {
                                    "type": "OR",
                                    "values": [
                                        {
                                            "key": "plan",
                                            "type": "person",
                                            "value": "A",
                                            "negation": False,
                                            "operator": "exact",
                                            "conditionHash": "nest_ha_003",
                                        },
                                        {
                                            "key": "plan",
                                            "type": "person",
                                            "value": "B",
                                            "negation": False,
                                            "operator": "exact",
                                            "conditionHash": "nest_hb_004",
                                        },
                                    ],
                                },
                            ],
                        }
                    ],
                },
                ["maxif(latest_matches"],
                ["intersect distinct", "union distinct"],
            ),
            (
                # Deeply nested AND-of-AND with different-key (non-mergeable) props → single scan
                "deeply_nested_single_scan",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "email",
                                            "type": "person",
                                            "value": "@x.com",
                                            "negation": False,
                                            "operator": "icontains",
                                            "conditionHash": "deep_001",
                                        },
                                        {
                                            "key": "plan",
                                            "type": "person",
                                            "value": "A",
                                            "negation": False,
                                            "operator": "exact",
                                            "conditionHash": "deep_002",
                                        },
                                    ],
                                },
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "country",
                                            "type": "person",
                                            "value": "US",
                                            "negation": False,
                                            "operator": "exact",
                                            "conditionHash": "deep_003",
                                        },
                                        {
                                            "key": "role",
                                            "type": "person",
                                            "value": "admin",
                                            "negation": False,
                                            "operator": "exact",
                                            "conditionHash": "deep_004",
                                        },
                                    ],
                                },
                            ],
                        }
                    ],
                },
                ["maxif(latest_matches"],
                ["intersect distinct", "union distinct"],
            ),
        ]
    )
    def test_single_scan_optimization(
        self,
        name: str,
        cohort_filters: dict,
        expected_present: list[str],
        expected_absent: list[str],
    ) -> None:
        cohort = Cohort.objects.create(team=self.team, name=f"Test {name}", filters={"properties": cohort_filters})
        query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse").lower()

        for substring in expected_present:
            self.assertIn(substring, query_str)
        for substring in expected_absent:
            self.assertNotIn(substring, query_str)

    def _seed_precalculated_person_properties(self, rows: list[tuple[UUID, str, bool]]) -> None:
        """Seed (person_id, condition, matches) rows for the current team."""
        timestamp = dt.datetime(2026, 1, 1)
        payload = [
            (self.team.pk, str(person_id), str(person_id), condition, 1 if matches else 0, "test", timestamp, offset)
            for offset, (person_id, condition, matches) in enumerate(rows)
        ]
        sync_execute(
            "INSERT INTO precalculated_person_properties "
            "(team_id, distinct_id, person_id, condition, matches, source, _timestamp, _offset) VALUES",
            payload,
        )

    def _realtime_cohort_members(self, cohort: Cohort) -> set[str]:
        """Execute a realtime cohort's current-members query and return the matched person_ids."""
        query = HogQLRealtimeCohortQuery(cohort=cohort).get_query()
        context = HogQLContext(
            team_id=self.team.pk, enable_select_queries=True, limit_context=LimitContext.COHORT_CALCULATION
        )
        sql, _ = prepare_and_print_ast(query, context, "clickhouse")
        return {str(row[0]) for row in sync_execute(sql, context.values)}

    def test_single_scan_membership_matches_boolean_semantics(self) -> None:
        """Execute the single-scan query against seeded data and assert who actually matches.

        String assertions can't catch a wrong argMax pick, a broken countIf, or an AND/OR
        threshold flip — all would produce valid SQL and the wrong cohort. This seeds rows and
        checks membership directly.
        """
        sync_execute(_PRECALCULATED_PERSON_PROPERTIES_TEST_DDL)
        sync_execute("TRUNCATE TABLE precalculated_person_properties")
        try:
            and_all, and_two = uuid4(), uuid4()
            or_one, or_none = uuid4(), uuid4()
            self._seed_precalculated_person_properties(
                [
                    # AND cohort (hashes A, B, C): all three vs only two
                    (and_all, "exec_A", True),
                    (and_all, "exec_B", True),
                    (and_all, "exec_C", True),
                    (and_two, "exec_A", True),
                    (and_two, "exec_B", True),
                    (and_two, "exec_C", False),
                    # OR cohort (hashes D, E): one of two vs none
                    (or_one, "exec_D", True),
                    (or_one, "exec_E", False),
                    (or_none, "exec_D", False),
                    (or_none, "exec_E", False),
                ]
            )

            and_cohort = Cohort.objects.create(
                team=self.team,
                name="exec AND",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "a",
                                        "type": "person",
                                        "value": "x",
                                        "negation": False,
                                        "operator": "exact",
                                        "conditionHash": "exec_A",
                                    },
                                    {
                                        "key": "b",
                                        "type": "person",
                                        "value": "y",
                                        "negation": False,
                                        "operator": "exact",
                                        "conditionHash": "exec_B",
                                    },
                                    {
                                        "key": "c",
                                        "type": "person",
                                        "value": "z",
                                        "negation": False,
                                        "operator": "exact",
                                        "conditionHash": "exec_C",
                                    },
                                ],
                            }
                        ],
                    }
                },
            )
            and_members = self._realtime_cohort_members(and_cohort)
            self.assertIn(str(and_all), and_members)  # matched all 3
            self.assertNotIn(str(and_two), and_members)  # matched only 2 of 3

            or_cohort = Cohort.objects.create(
                team=self.team,
                name="exec OR",
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "key": "d",
                                        "type": "person",
                                        "value": "x",
                                        "negation": False,
                                        "operator": "exact",
                                        "conditionHash": "exec_D",
                                    },
                                    {
                                        "key": "e",
                                        "type": "person",
                                        "value": "y",
                                        "negation": False,
                                        "operator": "exact",
                                        "conditionHash": "exec_E",
                                    },
                                ],
                            }
                        ],
                    }
                },
            )
            or_members = self._realtime_cohort_members(or_cohort)
            self.assertIn(str(or_one), or_members)  # matched 1 of 2
            self.assertNotIn(str(or_none), or_members)  # matched neither
        finally:
            sync_execute("DROP TABLE IF EXISTS precalculated_person_properties")

    def test_single_scan_argmax_latest_write_wins(self) -> None:
        """argMax picks the row with the highest (_timestamp, _offset), so the latest write wins.

        Seeds two rows per (person, condition): an earlier row with one matches value and a later row
        with the opposite. Asserts membership reflects the latest row, not the earlier one.
        The helper assigns _offset via enumerate, so a later list entry beats an earlier one.
        """
        sync_execute(_PRECALCULATED_PERSON_PROPERTIES_TEST_DDL)
        sync_execute("TRUNCATE TABLE precalculated_person_properties")
        try:
            flipped_out, flipped_in = uuid4(), uuid4()
            self._seed_precalculated_person_properties(
                [
                    # flipped_out: early True then late False → excluded
                    (flipped_out, "exec_F", True),
                    (flipped_out, "exec_F", False),
                    # flipped_in: early False then late True → included
                    (flipped_in, "exec_F", False),
                    (flipped_in, "exec_F", True),
                ]
            )

            cohort = Cohort.objects.create(
                team=self.team,
                name="argmax flip",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "f",
                                        "type": "person",
                                        "value": "x",
                                        "negation": False,
                                        "operator": "exact",
                                        "conditionHash": "exec_F",
                                    }
                                ],
                            }
                        ],
                    }
                },
            )
            members = self._realtime_cohort_members(cohort)
            self.assertNotIn(str(flipped_out), members)  # latest write was False
            self.assertIn(str(flipped_in), members)  # latest write was True
        finally:
            sync_execute("DROP TABLE IF EXISTS precalculated_person_properties")

    def test_nested_boolean_single_scan_membership(self) -> None:
        """Execute the nested-boolean single scan and assert membership for `(A AND B) OR (C AND D)`.

        This shape used to fall through to the INTERSECT/UNION DISTINCT path (the OOM source); the
        boolean-tree single scan must return the same person set without those set operations.
        """
        sync_execute(_PRECALCULATED_PERSON_PROPERTIES_TEST_DDL)
        sync_execute("TRUNCATE TABLE precalculated_person_properties")
        try:
            ab, cd, c_only, a_only = uuid4(), uuid4(), uuid4(), uuid4()
            self._seed_precalculated_person_properties(
                [
                    (ab, "exec_A", True),
                    (ab, "exec_B", True),  # matches first branch
                    (cd, "exec_C", True),
                    (cd, "exec_D", True),  # matches second branch
                    (c_only, "exec_C", True),  # half of second branch only
                    (a_only, "exec_A", True),  # half of first branch only
                ]
            )

            def leaf(key: str, condition_hash: str) -> dict:
                return {
                    "key": key,
                    "type": "person",
                    "value": "x",
                    "negation": False,
                    "operator": "exact",
                    "conditionHash": condition_hash,
                }

            cohort = Cohort.objects.create(
                team=self.team,
                name="nested",
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {"type": "AND", "values": [leaf("k1", "exec_A"), leaf("k2", "exec_B")]},
                                    {"type": "AND", "values": [leaf("k3", "exec_C"), leaf("k4", "exec_D")]},
                                ],
                            }
                        ],
                    }
                },
            )
            query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse")
            self.assertNotIn("INTERSECT DISTINCT", query_str)
            self.assertNotIn("UNION DISTINCT", query_str)

            members = self._realtime_cohort_members(cohort)
            self.assertIn(str(ab), members)  # A AND B
            self.assertIn(str(cd), members)  # C AND D
            self.assertNotIn(str(c_only), members)  # C without D
            self.assertNotIn(str(a_only), members)  # A without B
        finally:
            sync_execute("DROP TABLE IF EXISTS precalculated_person_properties")

    def test_nested_boolean_single_scan_and_merged_leaf_membership(self) -> None:
        """Exercise the AND-merged leaf (countIf(...) = N) inside the boolean tree.

        `(email~@gmail AND email~.com) AND plan` nested under a top-level OR: the same-key email
        pair merges into one AND-merged leaf, which the tree must render as
        `countIf(latest_matches = 1 AND condition IN (g, c)) = 2` — a person matching only one of
        the two merged hashes must be excluded.
        """

        def leaf(key: str, value: str, operator: str, condition_hash: str) -> dict:
            return {
                "key": key,
                "type": "person",
                "value": value,
                "negation": False,
                "operator": operator,
                "conditionHash": condition_hash,
            }

        sync_execute(_PRECALCULATED_PERSON_PROPERTIES_TEST_DDL)
        sync_execute("TRUNCATE TABLE precalculated_person_properties")
        try:
            both, one_only, country_only = uuid4(), uuid4(), uuid4()
            self._seed_precalculated_person_properties(
                [
                    (both, "m_g", True),
                    (both, "m_c", True),
                    (both, "plan_x", True),  # matches the AND-merged email pair + plan
                    (one_only, "m_g", True),
                    (one_only, "m_c", False),
                    (one_only, "plan_x", True),  # missed one of the merged hashes
                    (country_only, "country_y", True),  # matches the other OR branch
                ]
            )
            cohort = Cohort.objects.create(
                team=self.team,
                name="and-merged",
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "type": "AND",
                                        "values": [
                                            {
                                                "type": "AND",
                                                "values": [
                                                    leaf("email", "@gmail", "icontains", "m_g"),
                                                    leaf("email", ".com", "icontains", "m_c"),
                                                ],
                                            },
                                            {"type": "AND", "values": [leaf("plan", "x", "exact", "plan_x")]},
                                        ],
                                    },
                                    {"type": "AND", "values": [leaf("country", "y", "exact", "country_y")]},
                                ],
                            }
                        ],
                    }
                },
            )
            query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse").lower()
            self.assertNotIn("intersect distinct", query_str)
            self.assertNotIn("union distinct", query_str)
            self.assertIn("countif(", query_str)  # AND-merged leaf renders as countIf(...) = N

            members = self._realtime_cohort_members(cohort)
            self.assertIn(str(both), members)  # matched both merged hashes + plan
            self.assertIn(str(country_only), members)  # other OR branch
            self.assertNotIn(str(one_only), members)  # missed one merged hash → AND-merged leaf fails
        finally:
            sync_execute("DROP TABLE IF EXISTS precalculated_person_properties")

    def test_nested_negated_leaf_falls_through(self) -> None:
        """A negated leaf buried in a nested group must force the parent multi-subquery path.

        The single-scan tree can't express negation, so any nested negated person property must
        make `_build_boolean_tree_query` return None and fall through — not silently drop the
        negation and produce a wrong cohort.
        """
        cohort = Cohort.objects.create(
            team=self.team,
            name="nested-negated",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "OR",
                                    "values": [
                                        {
                                            "key": "email",
                                            "type": "person",
                                            "value": "@x",
                                            "negation": False,
                                            "operator": "icontains",
                                            "conditionHash": "nn_h1",
                                        }
                                    ],
                                },
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "plan",
                                            "type": "person",
                                            "value": "A",
                                            "negation": False,
                                            "operator": "exact",
                                            "conditionHash": "nn_h2",
                                        },
                                        {
                                            "key": "name",
                                            "type": "person",
                                            "value": "spam",
                                            "negation": True,
                                            "operator": "icontains",
                                            "conditionHash": "nn_h3",
                                        },
                                    ],
                                },
                            ],
                        }
                    ],
                }
            },
        )
        query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse").lower()
        # Tree path must NOT fire — a negated leaf forces the parent set-operation path.
        self.assertNotIn("maxif(latest_matches", query_str)

    def test_nested_or_under_and_membership(self) -> None:
        """Execution test for `(X OR Y) AND (A OR B)` — the shape flagged in the parameterized
        test as the threshold-flip risk.

        The tree renders it as `maxIf(...X,Y...) = 1 AND maxIf(...A,B...) = 1`, NOT a flat
        `countIf >= 4` threshold that would wrongly require all four. A person matching only X
        and A (one from each OR branch) must be IN; one matching X and Y but not A or B must be OUT.
        """
        sync_execute(_PRECALCULATED_PERSON_PROPERTIES_TEST_DDL)
        sync_execute("TRUNCATE TABLE precalculated_person_properties")
        try:
            x_and_a, x_and_y, a_and_b, neither = uuid4(), uuid4(), uuid4(), uuid4()
            self._seed_precalculated_person_properties(
                [
                    (x_and_a, "or_X", True),
                    (x_and_a, "or_A", True),  # one from each OR branch → should match
                    (x_and_y, "or_X", True),
                    (x_and_y, "or_Y", True),  # both from first branch, none from second → no match
                    (a_and_b, "or_A", True),
                    (a_and_b, "or_B", True),  # both from second branch, none from first → no match
                    (neither, "or_X", False),  # matches nothing
                ]
            )

            def leaf(key: str, condition_hash: str) -> dict:
                return {
                    "key": key,
                    "type": "person",
                    "value": "x",
                    "negation": False,
                    "operator": "exact",
                    "conditionHash": condition_hash,
                }

            cohort = Cohort.objects.create(
                team=self.team,
                name="or-under-and",
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"type": "OR", "values": [leaf("k1", "or_X"), leaf("k2", "or_Y")]},
                                    {"type": "OR", "values": [leaf("k3", "or_A"), leaf("k4", "or_B")]},
                                ],
                            }
                        ],
                    }
                },
            )
            query_str = HogQLRealtimeCohortQuery(cohort=cohort).query_str("clickhouse")
            self.assertNotIn("INTERSECT DISTINCT", query_str)
            self.assertNotIn("UNION DISTINCT", query_str)

            members = self._realtime_cohort_members(cohort)
            self.assertIn(str(x_and_a), members)  # one from each OR branch
            self.assertNotIn(str(x_and_y), members)  # both from first branch only
            self.assertNotIn(str(a_and_b), members)  # both from second branch only
            self.assertNotIn(str(neither), members)  # no match
        finally:
            sync_execute("DROP TABLE IF EXISTS precalculated_person_properties")

    @parameterized.expand(
        [
            # A merged child's internal boolean type must match the top-level operator to flatten.
            # (child_is_or, top_operator, should_flatten)
            ("or_child_under_or", True, PropertyOperatorType.OR, True),
            ("and_child_under_and", False, PropertyOperatorType.AND, True),
            ("or_child_under_and", True, PropertyOperatorType.AND, False),
            ("and_child_under_or", False, PropertyOperatorType.OR, False),
        ]
    )
    def test_collect_person_property_hashes_operator_mismatch_guard(
        self, _name: str, child_is_or: bool, top_operator: PropertyOperatorType, should_flatten: bool
    ) -> None:
        """A merged child encodes its own AND/OR across multiple hashes. The collector must only
        flatten it when the child's boolean type matches the top-level operator; a mismatch falls
        through (returns None) so the parent path expresses the nested boolean correctly.

        Cohort preprocessing currently sets `_is_or_group=True` on same-key merges, so the
        `and_child_under_or` direction isn't reachable end-to-end — this exercises the guard
        directly to keep both directions covered.
        """
        cohort = Cohort.objects.create(
            team=self.team,
            name="guard",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "x",
                                    "negation": False,
                                    "operator": "exact",
                                    "conditionHash": "h0",
                                }
                            ],
                        }
                    ],
                }
            },
        )
        query = HogQLRealtimeCohortQuery(cohort=cohort)

        def merged_prop(key: str, hashes: list[str]) -> Property:
            prop = Property(key=key, type="person", value="x", operator="exact", conditionHash=hashes[0])
            prop._merged_condition_hashes = hashes  # type: ignore[attr-defined]
            prop._is_or_group = child_is_or  # type: ignore[attr-defined]
            return prop

        group = PropertyGroup(
            type=top_operator,
            values=[merged_prop("email", ["h1", "h2"]), merged_prop("plan", ["h3", "h4"])],
        )
        result = query._collect_person_property_hashes(group)

        if should_flatten:
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(set(result[0]), {"h1", "h2", "h3", "h4"})
        else:
            self.assertIsNone(result)
