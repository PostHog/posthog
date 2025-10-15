from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery
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
