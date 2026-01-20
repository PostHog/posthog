from posthog.test.base import BaseTest, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from clickhouse_driver.errors import SocketTimeoutError
from parameterized import parameterized
from pydantic import (
    BaseModel,
    ValidationError as PydanticValidationError,
)
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.hogql.hogql import HogQLContext

from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
    EstimatedQueryExecutionTimeTooLong,
    QuerySizeExceeded,
)
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.cohort.util import (
    CohortErrorCode,
    get_all_cohort_dependencies,
    get_friendly_error_message,
    get_static_cohort_size,
    parse_error_code,
    print_cohort_hogql_query,
    simplified_cohort_filter_properties,
    sort_cohorts_topologically,
)

MISSING_COHORT_ID = 12345


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    is_static = kwargs.pop("is_static", False)
    cohort = Cohort.objects.create(team=team, name=name, groups=groups, is_static=is_static)
    return cohort


class TestCohortUtils(BaseTest):
    def test_simplified_cohort_filter_properties_static_cohort(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"name": "test", "name": "test"},
        )
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True)
        flush_persons_and_events()
        cohort.insert_users_by_list(["p1"])

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": False,
                        "type": "static-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_static_cohort_with_negation(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"name": "test", "name": "test"},
        )
        cohort = _create_cohort(team=self.team, name="cohort1", groups=[], is_static=True)
        flush_persons_and_events()
        cohort.insert_users_by_list(["p1"])

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "static-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_precalculated_cohort(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": False,
                        "type": "precalculated-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_precalculated_cohort_negated(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "precalculated-cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_non_precalculated_cohort_with_behavioural_filter(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "name", "value": "test", "type": "person"},
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_interval": "day",
                            "time_value": 8,
                            "seq_time_interval": "day",
                            "seq_time_value": 3,
                            "seq_event": "$pageview",
                            "seq_event_type": "events",
                            "value": "performed_event_sequence",
                            "type": "behavioral",
                        },
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": False,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

        # with negation

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_non_precalculated_cohort_with_cohort_filter(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "name", "value": "test", "type": "person"},
                        {
                            "key": "id",
                            "value": cohort1.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "name", "value": "test", "type": "person"}],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "id",
                                "value": cohort1.pk,
                                "type": "cohort",
                                "negation": True,
                            },
                        ],
                    },
                ],
            },
        )

        # with negation

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_simplified_cohort_filter_properties_non_precalculated_cohort_with_only_person_property_filters(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohortCeption",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "name", "value": "test", "type": "person"}],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {"key": "name2", "value": "test", "type": "person"},
                                {"key": "name3", "value": "test", "type": "person"},
                            ],
                        },
                    ],
                }
            },
        )

        cohort.calculate_people_ch(pending_version=0)

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=False)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [{"key": "name", "value": "test", "type": "person"}],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {"key": "name2", "value": "test", "type": "person"},
                            {"key": "name3", "value": "test", "type": "person"},
                        ],
                    },
                ],
            },
        )

        # with negation

        result = simplified_cohort_filter_properties(cohort, self.team, is_negated=True)

        self.assertEqual(
            result.to_dict(),
            {
                "type": "AND",
                "values": [
                    {
                        "key": "id",
                        "negation": True,
                        "type": "cohort",
                        "value": cohort.pk,
                    }
                ],
            },
        )

    def test_print_cohort_hogql_query_includes_settings(self):
        """Test that cohort queries include HogQL global settings"""
        # Create a cohort with a HogQL query (simulating a funnel-to-cohort conversion)
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Funnel Cohort",
            query={
                "kind": "ActorsQuery",
                "source": {
                    "kind": "FunnelsActorsQuery",
                    "source": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "$pageview"},
                            {"kind": "EventsNode", "event": "$identify"},
                        ],
                        "interval": "day",
                        "dateRange": {"date_from": "-30d"},
                        "funnelsFilter": {
                            "funnelVizType": "steps",
                            "funnelWindowInterval": 1,
                            "funnelWindowIntervalUnit": "day",
                        },
                    },
                    "funnelStep": 2,
                },
            },
        )

        context = HogQLContext(team_id=self.team.id, enable_select_queries=True)

        # Generate the SQL
        sql = print_cohort_hogql_query(cohort, context, team=self.team)

        # Assert that settings are included
        self.assertIn("SETTINGS", sql)
        self.assertIn("transform_null_in=1", sql)

        # Also check for other critical settings
        self.assertIn("readonly=2", sql)
        self.assertIn("max_execution_time=60", sql)
        self.assertIn("allow_experimental_object_type=1", sql)
        self.assertIn("optimize_min_equality_disjunction_chain_length=4294967295", sql)

    def test_get_static_cohort_size_uses_specified_database(self):
        cohort = _create_cohort(team=self.team, name="test_cohort", groups=[], is_static=True)

        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.using.return_value = mock_qs
        mock_qs.count.return_value = 42

        with patch("posthog.models.cohort.util.CohortPeople.objects", mock_qs):
            result = get_static_cohort_size(cohort_id=cohort.id, team_id=self.team.id, using_database="test_db")

        mock_qs.using.assert_called_once_with("test_db")
        self.assertEqual(result, 42)

    def test_get_static_cohort_size_without_database_does_not_call_using(self):
        cohort = _create_cohort(team=self.team, name="test_cohort", groups=[], is_static=True)

        mock_qs = MagicMock()
        mock_qs.filter.return_value = mock_qs
        mock_qs.count.return_value = 10

        with patch("posthog.models.cohort.util.CohortPeople.objects", mock_qs):
            result = get_static_cohort_size(cohort_id=cohort.id, team_id=self.team.id)

        mock_qs.using.assert_not_called()
        self.assertEqual(result, 10)

    def test_print_cohort_hogql_query_raises_error_on_mixed_id_types_in_union(self):
        """Test that mixed ID types in UNION queries are rejected"""
        from posthog.hogql import ast

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Mixed UNION Cohort",
            query={
                "kind": "ActorsQuery",
                "source": {
                    "kind": "FunnelsActorsQuery",
                    "source": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "$pageview"},
                            {"kind": "EventsNode", "event": "$identify"},
                        ],
                        "interval": "day",
                        "dateRange": {"date_from": "-30d"},
                    },
                    "funnelStep": 2,
                },
            },
        )

        context = HogQLContext(team_id=self.team.id, enable_select_queries=True)

        # Mock get_query_runner to return a mock runner with our UNION query
        def mock_get_query_runner(query, team, limit_context=None):
            mock_runner = MagicMock()
            # Create a UNION with mixed ID types
            # First SELECT returns person_id, second SELECT returns distinct_id
            select1 = ast.SelectQuery(
                select=[ast.Alias(expr=ast.Field(chain=["person_id"]), alias="person_id")],
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            )
            select2 = ast.SelectQuery(
                select=[ast.Alias(expr=ast.Field(chain=["distinct_id"]), alias="distinct_id")],
                select_from=ast.JoinExpr(table=ast.Field(chain=["raw_person_distinct_ids"])),
            )
            # Properly structured SelectSetQuery with initial and subsequent queries
            mock_runner.to_query.return_value = ast.SelectSetQuery(
                initial_select_query=select1,
                subsequent_select_queries=[ast.SelectSetNode(set_operator="UNION ALL", select_query=select2)],
            )
            return mock_runner

        with patch("posthog.hogql_queries.query_runner.get_query_runner", mock_get_query_runner):
            # Should raise ValueError with clear message about mixed ID types
            with self.assertRaises(ValueError) as cm:
                print_cohort_hogql_query(cohort, context, team=self.team)

        self.assertIn("UNION queries with mixed ID types", str(cm.exception))
        self.assertIn("not currently supported", str(cm.exception))

    def test_print_cohort_hogql_query_with_table_without_id_columns(self):
        """Test that queries without person_id, actor_id, id, or distinct_id columns raise an error"""
        from posthog.hogql import ast

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test No ID Columns Cohort",
            query={
                "kind": "ActorsQuery",
                "source": {
                    "kind": "FunnelsActorsQuery",
                    "source": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "$pageview"},
                            {"kind": "EventsNode", "event": "$identify"},
                        ],
                        "interval": "day",
                        "dateRange": {"date_from": "-30d"},
                    },
                    "funnelStep": 2,
                },
            },
        )

        context = HogQLContext(team_id=self.team.id, enable_select_queries=True)

        # Mock get_query_runner to return a query with no recognizable ID columns
        def mock_get_query_runner(query, team, limit_context=None):
            mock_runner = MagicMock()
            # SELECT with only non-ID columns
            select_query = ast.SelectQuery(
                select=[ast.Alias(expr=ast.Field(chain=["some_column"]), alias="some_column")],
                select_from=ast.JoinExpr(table=ast.Field(chain=["some_table"])),
            )
            mock_runner.to_query.return_value = select_query
            return mock_runner

        with patch("posthog.hogql_queries.query_runner.get_query_runner", mock_get_query_runner):
            # Should raise ValueError about missing ID columns
            with self.assertRaises(ValueError) as cm:
                print_cohort_hogql_query(cohort, context, team=self.team)

        self.assertIn("Could not find a person_id, actor_id, id, or distinct_id column", str(cm.exception))

    def test_print_cohort_hogql_query_with_distinct_id_column(self):
        """Test that queries with explicit distinct_id column are wrapped with person_distinct_id2 lookup"""
        from posthog.hogql import ast

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Distinct ID Column Cohort",
            query={
                "kind": "ActorsQuery",
                "source": {
                    "kind": "FunnelsActorsQuery",
                    "source": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "$pageview"},
                            {"kind": "EventsNode", "event": "$identify"},
                        ],
                        "interval": "day",
                        "dateRange": {"date_from": "-30d"},
                    },
                    "funnelStep": 2,
                },
            },
        )

        context = HogQLContext(team_id=self.team.id, enable_select_queries=True)

        # Mock get_query_runner to return a query with explicit distinct_id column
        def mock_get_query_runner(query, team, limit_context=None):
            mock_runner = MagicMock()
            # Query with explicit distinct_id column (not SELECT *)
            select_query = ast.SelectQuery(
                select=[ast.Alias(expr=ast.Field(chain=["distinct_id"]), alias="distinct_id")],
                select_from=ast.JoinExpr(table=ast.Field(chain=["raw_person_distinct_ids"])),
            )
            mock_runner.to_query.return_value = select_query
            return mock_runner

        with patch("posthog.hogql_queries.query_runner.get_query_runner", mock_get_query_runner):
            result = print_cohort_hogql_query(cohort, context, team=self.team)

        # Should wrap with person_distinct_id2 lookup
        self.assertIn("person_distinct_id2", result)
        self.assertIn("argMax(person_id, version) as actor_id", result)
        self.assertIn("WHERE distinct_id IN", result)
        # Should include settings
        self.assertIn("SETTINGS", result)

    def test_print_cohort_hogql_query_with_select_star_raises_error(self):
        """Test that SELECT * queries without explicit ID columns raise an error"""
        from posthog.hogql import ast

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test SELECT * Cohort",
            query={
                "kind": "ActorsQuery",
                "source": {
                    "kind": "FunnelsActorsQuery",
                    "source": {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "$pageview"},
                            {"kind": "EventsNode", "event": "$identify"},
                        ],
                        "interval": "day",
                        "dateRange": {"date_from": "-30d"},
                    },
                    "funnelStep": 2,
                },
            },
        )

        context = HogQLContext(team_id=self.team.id, enable_select_queries=True)

        # Mock get_query_runner to return a query with SELECT * from a table without known ID handling
        def mock_get_query_runner(query, team, limit_context=None):
            mock_runner = MagicMock()
            # SELECT * from a table that's not events or persons should raise an error
            select_query = ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["some_other_table"])),
            )
            mock_runner.to_query.return_value = select_query
            return mock_runner

        with patch("posthog.hogql_queries.query_runner.get_query_runner", mock_get_query_runner):
            # Should raise ValueError about missing ID columns
            with self.assertRaises(ValueError) as cm:
                print_cohort_hogql_query(cohort, context, team=self.team)

        self.assertIn("Could not find a person_id, actor_id, id, or distinct_id column", str(cm.exception))


class TestDependentCohorts(BaseTest):
    def test_dependent_cohorts_for_simple_cohort(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        self.assertEqual(get_all_cohort_dependencies(cohort), [])

    def test_dependent_cohorts_for_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}],
        )

        self.assertEqual(get_all_cohort_dependencies(cohort1), [])
        self.assertEqual(get_all_cohort_dependencies(cohort2), [cohort1])

    def test_dependent_cohorts_for_deeply_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort2",
            groups=[{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohort3",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        }
                    ]
                }
            ],
        )

        self.assertEqual(get_all_cohort_dependencies(cohort1), [])
        self.assertEqual(get_all_cohort_dependencies(cohort2), [cohort1])
        self.assertEqual(get_all_cohort_dependencies(cohort3), [cohort2, cohort1])

    def test_dependent_cohorts_for_circular_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        }
                    ]
                }
            ],
        )

        cohort1.groups = [{"properties": [{"key": "id", "value": cohort3.pk, "type": "cohort"}]}]
        cohort1.save()

        self.assertEqual(get_all_cohort_dependencies(cohort3), [cohort2, cohort1])
        self.assertEqual(get_all_cohort_dependencies(cohort2), [cohort1, cohort3])
        self.assertEqual(get_all_cohort_dependencies(cohort1), [cohort3, cohort2])

    def test_dependent_cohorts_for_complex_nested_cohort(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {"key": "name", "value": "test2", "type": "person"},
                        {"key": "id", "value": cohort1.pk, "type": "cohort"},
                    ]
                }
            ],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {"key": "name", "value": "test3", "type": "person"},
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                    ]
                }
            ],
        )

        cohort4 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort1.pk,
                            "type": "cohort",
                            "negation": True,
                        }
                    ]
                }
            ],
        )

        cohort5 = _create_cohort(
            team=self.team,
            name="cohort4",
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort2.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                        {
                            "key": "id",
                            "value": cohort4.pk,
                            "type": "cohort",
                            "negation": True,
                        },
                    ]
                }
            ],
        )

        self.assertEqual(get_all_cohort_dependencies(cohort1), [])
        self.assertEqual(get_all_cohort_dependencies(cohort2), [cohort1])
        self.assertEqual(get_all_cohort_dependencies(cohort3), [cohort2, cohort1])
        self.assertEqual(get_all_cohort_dependencies(cohort4), [cohort1])
        self.assertEqual(get_all_cohort_dependencies(cohort5), [cohort4, cohort1, cohort2])

    def test_dependent_cohorts_ignore_invalid_ids(self):
        cohort1 = _create_cohort(
            team=self.team,
            name="cohort1",
            groups=[{"properties": [{"key": "name", "value": "test", "type": "person"}]}],
        )

        cohort2 = _create_cohort(
            team=self.team,
            name="cohort2",
            groups=[
                {
                    "properties": [
                        {"key": "id", "value": cohort1.pk, "type": "cohort"},
                        {"key": "id", "value": "invalid-key", "type": "cohort"},
                    ]
                }
            ],
        )

        cohort3 = _create_cohort(
            team=self.team,
            name="cohorte",
            groups=[
                {
                    "properties": [
                        {"key": "id", "value": cohort2.pk, "type": "cohort"},
                        {"key": "id", "value": "invalid-key", "type": "cohort"},
                    ]
                }
            ],
        )

        self.assertEqual(get_all_cohort_dependencies(cohort2), [cohort1])
        self.assertEqual(get_all_cohort_dependencies(cohort3), [cohort2, cohort1])


class TestSortCohortsTopologically(BaseTest):
    def test_sort_cohorts_topologically_with_missing_cohort(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort_with_missing_ref",
            groups=[{"properties": [{"key": "id", "value": MISSING_COHORT_ID, "type": "cohort"}]}],
        )

        cohort_ids = {cohort.pk}
        seen_cohorts_cache: dict[int, CohortOrEmpty] = {cohort.pk: cohort}

        result = sort_cohorts_topologically(cohort_ids, seen_cohorts_cache)

        self.assertEqual(result, [cohort.pk])

    def test_sort_cohorts_topologically_with_missing_cohort_in_cache(self):
        cohort = _create_cohort(
            team=self.team,
            name="cohort_with_missing_ref",
            groups=[{"properties": [{"key": "id", "value": MISSING_COHORT_ID, "type": "cohort"}]}],
        )

        dependent_cohorts = get_all_cohort_dependencies(cohort)
        all_cohort_ids = {dep.id for dep in dependent_cohorts}
        all_cohort_ids.add(cohort.id)

        seen_cohorts_cache: dict[int, CohortOrEmpty] = {dep.id: dep for dep in dependent_cohorts}
        seen_cohorts_cache[cohort.id] = cohort

        result = sort_cohorts_topologically(all_cohort_ids, seen_cohorts_cache)

        self.assertEqual(result, [cohort.pk])


class TestParseErrorCode(BaseTest):
    @parameterized.expand(
        [
            ("capacity", "ClickHouseAtCapacity", CohortErrorCode.CAPACITY),
            ("socket_timeout", "SocketTimeoutError", CohortErrorCode.INTERRUPTED),
            ("query_timeout", "ClickHouseQueryTimeOut", CohortErrorCode.TIMEOUT),
            ("estimated_timeout", "EstimatedQueryExecutionTimeTooLong", CohortErrorCode.TIMEOUT),
            ("memory_limit", "ClickHouseQueryMemoryLimitExceeded", CohortErrorCode.MEMORY_LIMIT),
            ("query_size", "QuerySizeExceeded", CohortErrorCode.QUERY_SIZE),
            ("pydantic_validation", "PydanticValidationError", CohortErrorCode.VALIDATION_ERROR),
            ("drf_validation", "DRFValidationError", CohortErrorCode.VALIDATION_ERROR),
            ("value_error", "ValueError", CohortErrorCode.UNKNOWN),
            ("clickhouse_regex", "ClickHouseRegexError", CohortErrorCode.INVALID_REGEX),
            ("clickhouse_memory", "ClickHouseMemoryError", CohortErrorCode.MEMORY_LIMIT),
            ("clickhouse_timeout", "ClickHouseTimeoutError", CohortErrorCode.TIMEOUT),
            ("clickhouse_type", "ClickHouseTypeError", CohortErrorCode.INCOMPATIBLE_TYPES),
            ("generic_exception", "Exception", CohortErrorCode.UNKNOWN),
        ]
    )
    def test_parse_error_code(self, _name: str, exception_type: str, expected_code: str):
        exception = self._create_exception(exception_type)
        result = parse_error_code(exception)
        self.assertEqual(result, expected_code)

    def _create_exception(self, exception_type: str) -> Exception:
        simple_exceptions: dict[str, type[Exception]] = {
            "ClickHouseAtCapacity": ClickHouseAtCapacity,
            "SocketTimeoutError": SocketTimeoutError,
            "ClickHouseQueryTimeOut": ClickHouseQueryTimeOut,
            "ClickHouseQueryMemoryLimitExceeded": ClickHouseQueryMemoryLimitExceeded,
            "QuerySizeExceeded": QuerySizeExceeded,
            "DRFValidationError": DRFValidationError,
            "ValueError": ValueError,
            "Exception": Exception,
        }

        if exception_type in simple_exceptions:
            return simple_exceptions[exception_type]("test")

        if exception_type == "EstimatedQueryExecutionTimeTooLong":
            return EstimatedQueryExecutionTimeTooLong()

        if exception_type == "PydanticValidationError":
            try:

                class TestModel(BaseModel):
                    value: int

                TestModel(value="not_an_int")
            except PydanticValidationError as e:
                return e
            raise AssertionError("Expected PydanticValidationError")

        clickhouse_code_names = {
            "ClickHouseRegexError": "CANNOT_COMPILE_REGEXP",
            "ClickHouseMemoryError": "MEMORY_LIMIT_EXCEEDED",
            "ClickHouseTimeoutError": "TIMEOUT_EXCEEDED",
            "ClickHouseTypeError": "NO_COMMON_TYPE",
        }

        if exception_type in clickhouse_code_names:
            exc = Exception("test")
            exc.code_name = clickhouse_code_names[exception_type]  # type: ignore
            return exc

        raise ValueError(f"Unknown exception type: {exception_type}")


class TestGetFriendlyErrorMessage(BaseTest):
    @parameterized.expand(
        [
            (CohortErrorCode.CAPACITY, "system was busy"),
            (CohortErrorCode.INTERRUPTED, "interrupted"),
            (CohortErrorCode.TIMEOUT, "terminated for taking too long"),
            (CohortErrorCode.MEMORY_LIMIT, "terminated for using too much memory"),
            (CohortErrorCode.QUERY_SIZE, "query that was too large"),
            (CohortErrorCode.VALIDATION_ERROR, "an error occurred"),
            (CohortErrorCode.INVALID_REGEX, "invalid regular expression"),
            (CohortErrorCode.INCOMPATIBLE_TYPES, "an error occurred"),
            (CohortErrorCode.NO_PROPERTIES, "no matching criteria"),
            (CohortErrorCode.UNKNOWN, "an error occurred"),
        ]
    )
    def test_get_friendly_error_message(self, error_code: str, expected_substring: str):
        message = get_friendly_error_message(error_code)
        assert message is not None
        self.assertIn(expected_substring, message.lower())

    def test_get_friendly_error_message_none(self):
        self.assertIsNone(get_friendly_error_message(None))

    def test_get_friendly_error_message_unknown_code(self):
        message = get_friendly_error_message("some_unknown_code")
        assert message is not None
        self.assertIn("an error occurred", message.lower())
