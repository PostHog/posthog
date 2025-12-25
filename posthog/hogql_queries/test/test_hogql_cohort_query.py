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

        # The 3 mergeable email icontains should be in a single merged query with IN clause
        # Looking at the IN clause specifically
        in_clause_count = query_str.lower().count("in(precalculated_person_properties.condition,")

        # Should have exactly 1 IN clause for the merged conditions
        self.assertEqual(in_clause_count, 1, "Should have exactly 1 IN clause for merged conditions")

        # Should have exactly 3 single condition checks (one for each non-mergeable property)
        single_condition_count = query_str.lower().count("equals(precalculated_person_properties.condition,")
        self.assertEqual(single_condition_count, 3, "Should have exactly 3 single condition checks")

        # Should use IN clause for merged conditions
        self.assertIn("in(precalculated_person_properties.condition,", query_str.lower())

        # The merged query should check for at least 1 match using countIf
        self.assertIn("countif", query_str.lower())

        # Should have UNION DISTINCT since we have non-mergeable properties too
        self.assertIn("UNION DISTINCT", query_str)

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
        # Should use countIf for counting matches
        self.assertIn("countif", query_str.lower())
        # For AND semantics, should check that ALL 3 conditions matched
        self.assertIn(", 3)", query_str)  # equals(countIf(...), 3)
        # Should NOT use UNION DISTINCT since properties are merged
        self.assertNotIn("UNION DISTINCT", query_str)

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

        # Should have 1 IN clause for ALL merged email properties (yahoo + protonmail + live = 3 hashes)
        in_clause_count = query_str.lower().count("in(precalculated_person_properties.condition,")
        self.assertEqual(in_clause_count, 1, "Should have exactly 1 IN clause for all merged email properties")

        # Verify the IN clause has a tuple with 3 values (all 3 hashes merged)
        # The pattern will be: tuple(%(hogql_val_X)s, %(hogql_val_Y)s, %(hogql_val_Z)s)

        # Match tuple with exactly 3 comma-separated parameter placeholders
        tuple_pattern = r"tuple\(%\(hogql_val_\d+\)s,\s*%\(hogql_val_\d+\)s,\s*%\(hogql_val_\d+\)s\)"
        self.assertRegex(query_str, tuple_pattern, "IN clause should have tuple with 3 values")

        # Should use UNION DISTINCT since we have multiple top-level groups
        self.assertIn("UNION DISTINCT", query_str)

        # Should have INTERSECT DISTINCT for the AND group (email + name)
        self.assertIn("INTERSECT DISTINCT", query_str)

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

        # Should have been deduplicated to a single condition
        # The IN clause should contain only one hash, not three
        in_clause_count = query_str.lower().count("in(precalculated_person_properties.condition,")
        self.assertEqual(in_clause_count, 1, "Should have exactly 1 IN clause after deduplication")

        # Should have HAVING countIf(...) = 1 (not 3) because duplicates were removed
        self.assertIn(", 1)", query_str)  # countIf(...), 1) in equals function

        # Should NOT use INTERSECT since all properties merged into one
        self.assertNotIn("INTERSECT DISTINCT", query_str)
