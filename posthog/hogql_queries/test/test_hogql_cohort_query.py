from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery, HogQLRealtimeCohortQuery
from posthog.models import Cohort


class TestHogQLCohortQuery(ClickhouseTestMixin, APIBaseTest):
    """Tests for HogQLCohortQuery, particularly the optimization for multiple person property filters."""

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

        # Should query persons table for person properties
        self.assertIn("persons", query_str)
        # Should have the email filter
        self.assertIn("email", query_str.lower())

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
        # Should join with person_distinct_id table for person mapping
        self.assertIn("person_distinct_id", query_str)
        # Should use argMax for getting latest person_id
        self.assertIn("argMax", query_str)
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
        # Should have event_count field
        self.assertIn("event_count", query_str)
        # Should have greaterOrEquals comparison with 5
        self.assertIn("greaterOrEquals(event_count, 5)", query_str)
        # Should have HAVING clause for count filtering
        self.assertIn("HAVING", query_str)
        # Should join with person_distinct_id table
        self.assertIn("person_distinct_id", query_str)

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
