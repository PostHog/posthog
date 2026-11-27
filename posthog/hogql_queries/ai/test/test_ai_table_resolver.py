import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, materialized
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.ai.ai_table_resolver import (
    AIEventsExpiredError,
    AIEventsNotFoundError,
    is_ai_events_enabled,
    query_ai_events,
)
from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.event_definitions.backend.models import PropertyDefinition


class TestIsAiEventsEnabled:
    @patch("posthog.hogql_queries.ai.ai_table_resolver.feature_enabled_or_false", return_value=True)
    def test_returns_true_when_flag_enabled(self, mock_flag):
        team = Mock(id=123, organization_id="org_abc")
        assert is_ai_events_enabled(team) is True
        mock_flag.assert_called_once_with(
            "ai-events-table-rollout",
            "123",
            groups={"organization": "org_abc"},
            group_properties={"organization": {"id": "org_abc"}},
            send_feature_flag_events=False,
        )

    @patch("posthog.hogql_queries.ai.ai_table_resolver.feature_enabled_or_false", return_value=False)
    def test_returns_false_when_flag_disabled(self, mock_flag):
        team = Mock(id=456, organization_id="org_xyz")
        assert is_ai_events_enabled(team) is False
        mock_flag.assert_called_once_with(
            "ai-events-table-rollout",
            "456",
            groups={"organization": "org_xyz"},
            group_properties={"organization": {"id": "org_xyz"}},
            send_feature_flag_events=False,
        )


# query_ai_events resolves the events-schema gate. On a legacy-schema run that gate falls through
# to an instance setting read from Postgres, which only stays off the wire while some earlier
# BaseTest has warmed its cache. Declare the access rather than depend on test order.
@pytest.mark.django_db
class TestQueryAiEvents:
    def _make_query(self):
        return ast.SelectQuery(
            select=[ast.Field(chain=["trace_id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events"),
            where=ast.Constant(value=True),
        )

    def _make_result(self, results):
        return Mock(results=results, columns=[])

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_returns_ai_events_result_when_data_found(self, mock_execute):
        ai_result = self._make_result([["trace-1"]])
        mock_execute.return_value = ai_result

        team = Mock(id=1, organization_id="org")
        result = query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
        )

        assert result is ai_result
        assert mock_execute.call_count == 1

    @patch("posthog.hogql_queries.ai.ai_table_resolver.use_new_events_schema", return_value=True)
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_falls_back_to_events_with_pinned_schema(self, mock_execute, _mock_use_new_events_schema):
        ai_result = self._make_result([])
        events_result = self._make_result([["trace-1"]])
        mock_execute.side_effect = [ai_result, events_result]

        team = Mock(id=1, organization_id="org")
        user = Mock()
        result = query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            user=user,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        assert result is events_result
        assert mock_execute.call_count == 2
        assert mock_execute.call_args.kwargs["context"].use_new_events_schema is True
        assert mock_execute.call_args.kwargs["context"].user is user
        assert all(call.kwargs["user"] is user for call in mock_execute.call_args_list)

    @patch("posthog.hogql_queries.ai.ai_table_resolver.use_new_events_schema", return_value=False)
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_raises_expired_when_ai_events_empty_but_events_has_rows(self, mock_execute, _mock_use_new_events_schema):
        # ai_events empty, events probe finds the row -> the data aged past the TTL.
        mock_execute.side_effect = [self._make_result([]), self._make_result([[1]])]

        team = Mock(id=1, organization_id="org")
        user = Mock()
        with pytest.raises(AIEventsExpiredError):
            query_ai_events(
                query=self._make_query(),
                placeholders={},
                team=team,
                user=user,
                query_type="TestQuery",
            )
        assert mock_execute.call_count == 2
        assert mock_execute.call_args.kwargs["context"].user is user
        assert all(call.kwargs["user"] is user for call in mock_execute.call_args_list)

    @patch("posthog.hogql_queries.ai.ai_table_resolver.use_new_events_schema", return_value=False)
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_raises_not_found_when_empty_in_both_tables(self, mock_execute, _mock_use_new_events_schema):
        mock_execute.side_effect = [self._make_result([]), self._make_result([])]

        team = Mock(id=1, organization_id="org")
        with pytest.raises(AIEventsNotFoundError):
            query_ai_events(
                query=self._make_query(),
                placeholders={},
                team=team,
                query_type="TestQuery",
            )
        assert mock_execute.call_count == 2

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_rewrites_placeholders_for_ai_events(self, mock_execute):
        mock_execute.return_value = self._make_result([["found"]])

        team = Mock(id=1, organization_id="org")
        placeholder = ast.Field(chain=["properties", "$ai_trace_id"])
        query_ai_events(
            query=self._make_query(),
            placeholders={"condition": placeholder},
            team=team,
            query_type="TestQuery",
        )

        # The placeholder should have been rewritten from properties.$ai_trace_id to trace_id
        actual_placeholders = mock_execute.call_args.kwargs.get("placeholders", {})
        rewritten = actual_placeholders["condition"]
        assert isinstance(rewritten, ast.Field)
        assert rewritten.chain == ["trace_id"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.use_new_events_schema", return_value=False)
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_rewrites_placeholders_for_events_fallback(self, mock_execute, _mock_use_new_events_schema):
        mock_execute.side_effect = [self._make_result([]), self._make_result([["found"]])]

        team = Mock(id=1, organization_id="org")
        # Use a native ai_events column name in the placeholder
        placeholder = ast.Field(chain=["trace_id"])
        query_ai_events(
            query=self._make_query(),
            placeholders={"condition": placeholder},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        # The events-table call should rewrite trace_id back to properties.$ai_trace_id
        actual_placeholders = mock_execute.call_args.kwargs.get("placeholders", {})
        rewritten = actual_placeholders["condition"]
        assert isinstance(rewritten, ast.Field)
        assert rewritten.chain == ["properties", "$ai_trace_id"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.use_new_events_schema", return_value=False)
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_rewrites_query_from_clause_for_events_fallback(self, mock_execute, _mock_use_new_events_schema):
        mock_execute.side_effect = [self._make_result([]), self._make_result([])]

        team = Mock(id=1, organization_id="org")
        query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        # The events-table call's FROM clause should have been rewritten to events
        actual_query = mock_execute.call_args.kwargs.get("query")
        assert isinstance(actual_query, ast.SelectQuery)
        assert actual_query.select_from is not None
        assert isinstance(actual_query.select_from.table, ast.Field)
        assert actual_query.select_from.table.chain == ["events"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_passes_optional_kwargs(self, mock_execute):
        mock_execute.return_value = self._make_result([["found"]])

        team = Mock(id=1, organization_id="org")
        timings = Mock()
        modifiers = Mock()
        limit_context = Mock()
        settings = Mock()
        workload = Mock()
        user = Mock()

        query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            settings=settings,
            workload=workload,
            user=user,
        )

        kwargs = mock_execute.call_args.kwargs
        assert kwargs["timings"] is timings
        assert kwargs["modifiers"] is modifiers
        assert kwargs["limit_context"] is limit_context
        assert kwargs["settings"] is settings
        assert kwargs["workload"] is workload
        assert kwargs["user"] is user

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_omits_unset_optional_kwargs(self, mock_execute):
        # Unset kwargs must NOT appear in the forwarded call so they don't override
        # execute_hogql_query's defaults (workload=DEFAULT, etc).
        mock_execute.return_value = self._make_result([["found"]])

        team = Mock(id=1, organization_id="org")
        query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
        )

        kwargs = mock_execute.call_args.kwargs
        assert "timings" not in kwargs
        assert "modifiers" not in kwargs
        assert "limit_context" not in kwargs
        assert "settings" not in kwargs
        assert "workload" not in kwargs
        assert kwargs["user"] is None


_PERSON_JOIN_QUERY = "SELECT person.properties.email FROM posthog.ai_events"


class TestQueryAiEventsPersonJoin(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("query_ai_events", query_ai_events, _PERSON_JOIN_QUERY, [("user@example.com",)], False),
            ("execute_hogql_query", execute_hogql_query, _PERSON_JOIN_QUERY, [("user@example.com",)], False),
            (
                "independent_persons_branch",
                execute_hogql_query,
                "SELECT properties.email, (SELECT count() FROM posthog.ai_events) FROM persons",
                [("user@example.com", 1)],
                True,
            ),
        ]
    )
    def test_person_materialized_columns_only_skipped_under_ai_events(
        self, _name, run_query, query, expected_results, reads_materialized_column
    ):
        with materialized("person", "email"):
            _create_person(distinct_ids=["person1"], team=self.team, properties={"email": "user@example.com"})
            bulk_create_ai_events(
                [
                    {
                        "event": "$ai_generation",
                        "team": self.team,
                        "distinct_id": "person1",
                        "properties": {"$ai_trace_id": "trace-1"},
                    }
                ]
            )

            result = run_query(
                query=parse_select(query),
                placeholders={},
                team=self.team,
                query_type="TestQuery",
            )

        assert result.results == expected_results
        assert ("pmat_email" in result.clickhouse) == reads_materialized_column


class TestQueryAiEventsTypedProperties(ClickhouseTestMixin, BaseTest):
    def _create_generations(self, table: str, *properties: dict[str, str | int | bool]) -> None:
        events = [
            {
                "event": "$ai_generation",
                "team": self.team,
                "distinct_id": f"example-user-{index}",
                "properties": event_properties,
            }
            for index, event_properties in enumerate(properties)
        ]
        if table == "events":
            for event in events:
                _create_event(**event)
        else:
            bulk_create_ai_events(events)

    @parameterized.expand(
        [
            (f"{table}_{property_type}_{comparison}", table, property_type, values, predicate)
            for table in ("events", "posthog.ai_events")
            for property_type, values, kept_literal, excluded_literal in (
                ("String", ("kept", "excluded"), "'kept'", "'excluded'"),
                ("Numeric", (7, 8), "7", "8"),
                ("Boolean", (True, False), "true", "false"),
                ("Duration", (7, 8), "'7'", "'8'"),
                (
                    "DateTime",
                    ("2024-04-05T06:07:08Z", "2024-04-06T06:07:08Z"),
                    "'2024-04-05T06:07:08Z'",
                    "'2024-04-06T06:07:08Z'",
                ),
            )
            for comparison, predicate in (("eq", f"value = {kept_literal}"), ("ne", f"value != {excluded_literal}"))
        ]
    )
    def test_cte_comparisons_exclude_missing_properties(
        self,
        _name: str,
        table: str,
        property_type: str,
        values: tuple[str | int | bool, str | int | bool],
        predicate: str,
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_value", property_type=property_type)
        self._create_generations(table, {"example_value": values[0]}, {"example_value": values[1]}, {})

        source = f"SELECT distinct_id, properties.example_value AS value FROM {table}"
        query = f"WITH projected AS ({source}) SELECT distinct_id FROM projected WHERE {predicate}"
        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [("example-user-0",)]

    def test_cte_comparison_excludes_missing_native_string_id(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="$ai_trace_id", property_type="Numeric")
        self._create_generations("posthog.ai_events", {"$ai_trace_id": "00123"}, {"$ai_trace_id": "00456"}, {})

        query = (
            "WITH traces AS (SELECT properties.$ai_trace_id AS value FROM posthog.ai_events) "
            "SELECT value FROM traces WHERE value != '00456'"
        )
        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [("00123",)]

    @parameterized.expand(
        [(table, projection) for table in ("events", "posthog.ai_events") for projection in ("cte", "subquery")]
    )
    def test_duration_property_through_projection(self, table: str, projection: str) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_duration", property_type="Duration")
        self._create_generations(table, {"example_duration": 123})

        source = f"SELECT properties.example_duration AS d FROM {table}"
        select = "SELECT toFloatOrZero(d), isNull(toDateTime(d))"
        query = (
            f"WITH durations AS ({source}) {select} FROM durations"
            if projection == "cte"
            else f"{select} FROM ({source})"
        )

        result = execute_hogql_query(
            query,
            team=self.team,
            workload=Workload.ONLINE,
        )

        assert result.results == [(123.0, True)]

    @parameterized.expand(
        [
            (table, projection, property_type, value, expected)
            for table in ("events", "posthog.ai_events")
            for projection in ("cte", "subquery")
            for property_type, value, expected in (
                ("Numeric", 123, (123.0, 123)),
                ("Boolean", True, (0.0, 0)),
                ("DateTime", "2024-04-05T06:07:08Z", (0.0, 0)),
            )
        ]
    )
    def test_typed_projection_inside_string_parser(
        self,
        table: str,
        projection: str,
        property_type: str,
        value: str | bool | int,
        expected: tuple[float | int, ...],
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_number", property_type=property_type)
        self._create_generations(table, {"example_number": value})

        source = f"SELECT properties.example_number AS n FROM {table}"
        select = "SELECT toFloatOrZero(n), toIntOrZero(n)"
        if property_type == "Numeric":
            select += ", toFloatOrDefault(n, 7), toIntOrDefault(n, 7)"
            expected += expected
        query = (
            f"WITH numbers AS ({source}) {select} FROM numbers" if projection == "cte" else f"{select} FROM ({source})"
        )

        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [expected]

    @parameterized.expand(
        [
            (
                f"{table}_{property_type}_{projection}_{order}_{via}",
                table,
                property_type,
                value,
                parser,
                expected,
                projection,
                order,
                via,
            )
            for table in ("events", "posthog.ai_events")
            for property_type, value, parser, expected in (
                ("Numeric", 123, "toFloatOrZero(value)", 123.0),
                ("DateTime", "2024-04-05T06:07:08Z", "toYear(toDateTime(value))", 2024),
            )
            for projection, order, via in (
                ("cte", "property_first", "direct"),
                ("cte", "null_first", "direct"),
                ("subquery", "property_first", "direct"),
                ("subquery", "null_first", "direct"),
                ("subquery", "null_first", "cte"),
                ("subquery", "null_first", "subquery"),
            )
        ]
    )
    def test_typed_property_in_union_projection(
        self,
        _name: str,
        table: str,
        property_type: str,
        value: str | int,
        parser: str,
        expected: float | int,
        projection: str,
        order: str,
        via: str,
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_value", property_type=property_type)
        self._create_generations(table, {"example_value": value})

        property_select = f"SELECT properties.example_value AS value FROM {table}"
        ctes = []
        if via == "cte":
            ctes.append(f"stored AS ({property_select})")
            property_select = "SELECT value FROM stored"
        elif via == "subquery":
            property_select = f"SELECT value FROM ({property_select})"
        branches = (property_select, "SELECT NULL AS value")
        union = " UNION ALL ".join(branches if order == "property_first" else reversed(branches))
        source = "combined" if projection == "cte" else f"({union})"
        query = f"SELECT {parser} FROM {source} WHERE value IS NOT NULL"
        if projection == "cte":
            ctes.append(f"combined AS ({union})")
        if ctes:
            query = f"WITH {', '.join(ctes)} {query}"
        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [(expected,)]

    @parameterized.expand(
        [
            (function, property_type, value, parser, expected, in_union)
            for function in ("coalesce", "COALESCE", "ifNull", "IFNULL", "ifnull")
            for property_type, value, parser, expected in (
                ("Numeric", 123, "toFloatOrZero(value)", 123.0),
                ("DateTime", "2024-04-05T06:07:08Z", "toYear(toDateTime(value))", 2024),
            )
            for in_union in (False, True)
        ]
    )
    def test_null_default_preserves_converted_property_type(
        self, function: str, property_type: str, value: str | int, parser: str, expected: float | int, in_union: bool
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_value", property_type=property_type)
        self._create_generations("posthog.ai_events", {"example_value": value})

        source = f"SELECT {function}(properties.example_value, NULL) AS value FROM posthog.ai_events"
        if in_union:
            source = f"SELECT NULL AS value UNION ALL {source}"
        query = f"SELECT {parser} FROM ({source}) WHERE value IS NOT NULL"
        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [(expected,)]

    def test_uppercase_null_default_keeps_raw_values_for_string_parser(self) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_value", property_type="Numeric")
        self._create_generations("posthog.ai_events", {"example_value": 123}, {})

        query = (
            "SELECT toIntOrZero(COALESCE(properties.example_value, '0')) FROM posthog.ai_events ORDER BY distinct_id"
        )
        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [(123,), (0,)]

    @parameterized.expand(
        [
            (
                "if_with_string_default",
                "Numeric",
                ("9",),
                "SELECT toIntOrZero(if(distinct_id = 'example-user-0', properties.example_value, '7')) "
                "FROM posthog.ai_events",
                9,
            ),
            (
                "any",
                "Numeric",
                ("9",),
                "SELECT toFloatOrZero(any(coalesce(properties.example_value, NULL))) FROM posthog.ai_events",
                9.0,
            ),
            (
                "max_cte",
                "Numeric",
                ("9", "10"),
                "WITH values AS (SELECT max(properties.example_value) AS value FROM posthog.ai_events) "
                "SELECT toIntOrZero(value) FROM values",
                9,
            ),
            (
                "searched_case",
                "DateTime",
                ("2024-04-05T06:07:08Z",),
                "SELECT toYear(toDateTime(CASE WHEN distinct_id = 'example-user-0' THEN properties.example_value "
                "WHEN distinct_id = 'other' THEN '2020-01-01' END)) FROM posthog.ai_events",
                2024,
            ),
            (
                "simple_case",
                "Numeric",
                ("9",),
                "SELECT toIntOrZero(CASE distinct_id WHEN 'example-user-0' THEN properties.example_value "
                "ELSE '7' END) FROM posthog.ai_events",
                9,
            ),
            (
                "max_if",
                "Numeric",
                ("9", "10", "99"),
                "SELECT toIntOrZero(maxIf(properties.example_value, distinct_id != 'example-user-2')) "
                "FROM posthog.ai_events",
                9,
            ),
            (
                "argmax",
                "Numeric",
                ("9", "10"),
                "SELECT toIntOrZero(argMax(properties.example_value, properties.example_value)) FROM posthog.ai_events",
                9,
            ),
            (
                "numeric_branch",
                "Numeric",
                ("9",),
                "SELECT if(true, properties.example_value, 0) FROM posthog.ai_events",
                9,
            ),
            (
                "aggregate_with_numeric_default",
                "Numeric",
                ("9", "10"),
                "SELECT max(coalesce(properties.example_value, 0)) FROM posthog.ai_events",
                10,
            ),
            (
                "conditional_with_nested_numeric_default",
                "Numeric",
                ("9",),
                "SELECT if(true, properties.example_value, coalesce(properties.example_value, 0)) FROM posthog.ai_events",
                9,
            ),
            (
                "arithmetic_branch",
                "Numeric",
                ("9",),
                "SELECT if(true, properties.example_value + 1, 0) FROM posthog.ai_events",
                10,
            ),
            (
                "scalar_subquery",
                "Numeric",
                ("9",),
                "SELECT if(true, (SELECT count() FROM posthog.ai_events WHERE properties.example_value > 7), 0)",
                1,
            ),
            (
                "numeric_cte_then_any",
                "Numeric",
                ("9",),
                "WITH projected AS (SELECT properties.example_value AS value FROM posthog.ai_events) "
                "SELECT toFloatOrZero(any(value)) FROM projected",
                9.0,
            ),
            (
                "datetime_cte_then_if",
                "DateTime",
                ("2024-04-05T06:07:08Z",),
                "WITH projected AS (SELECT distinct_id, properties.example_value AS value FROM posthog.ai_events) "
                "SELECT toYear(toDateTime(if(distinct_id = 'example-user-0', value, NULL))) FROM projected",
                2024,
            ),
        ]
    )
    def test_ai_property_types_inside_selection_functions(
        self, _name: str, property_type: str, values: tuple[str, ...], query: str, expected: float | int
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_value", property_type=property_type)
        properties: list[dict[str, str | int | bool]] = [{"example_value": value} for value in values]
        self._create_generations("posthog.ai_events", *properties)

        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [(expected,)]

    @parameterized.expand(
        [
            ("boolean", "example_flag", "Boolean", False, True),
            ("numeric", "example_number", "Numeric", 3, 4),
        ]
    )
    def test_filters_typed_custom_property(
        self, _name: str, key: str, property_type: str, match: bool | int, other: bool | int
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name=key, property_type=property_type)
        self._create_generations("posthog.ai_events", {key: match}, {key: other})

        result = query_ai_events(
            query=parse_select("SELECT {property} FROM posthog.ai_events WHERE {where_clause}"),
            placeholders={
                "property": ast.Field(chain=["properties", key]),
                "where_clause": property_to_expr({"type": "event", "key": key, "value": match}, self.team),
            },
            team=self.team,
            query_type="TestQuery",
            workload=Workload.ONLINE,
        )

        assert result.results == [(match,)]

    @parameterized.expand(
        [
            (
                "boolean",
                "$ai_is_error",
                "Boolean",
                True,
                False,
                "SELECT properties.$ai_is_error FROM posthog.ai_events WHERE properties.$ai_is_error = true",
            ),
            (
                "numeric",
                "$ai_total_tokens",
                "Numeric",
                123,
                100,
                "SELECT properties.$ai_total_tokens FROM posthog.ai_events WHERE properties.$ai_total_tokens > 100",
            ),
            (
                "boolean_cte",
                "example_flag",
                "Boolean",
                True,
                False,
                "WITH flags AS (SELECT properties.example_flag AS flag FROM posthog.ai_events) "
                "SELECT flag FROM flags WHERE flag = true",
            ),
        ]
    )
    def test_hogql_filters_typed_property(
        self, _name: str, key: str, property_type: str, match: bool | int, other: bool | int, query: str
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name=key, property_type=property_type)
        self._create_generations("posthog.ai_events", {key: match}, {key: other})

        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [(match,)]

    @parameterized.expand(
        [
            (
                "subquery",
                "posthog.ai_events",
                "SELECT toYear(toDateTime(d)) FROM (SELECT properties.example_date AS d FROM posthog.ai_events)",
                2024,
            ),
            (
                "cte",
                "posthog.ai_events",
                "WITH dated_events AS (SELECT properties.example_date AS d FROM posthog.ai_events) "
                "SELECT toYear(toDateTime(d)) FROM dated_events",
                2024,
            ),
            (
                "events_cte",
                "events",
                "WITH dated_events AS (SELECT properties.example_date AS d FROM events) "
                "SELECT toYear(toDateTime(d)) FROM dated_events",
                2024,
            ),
            (
                "scalar_cte",
                "posthog.ai_events",
                "SELECT toFloatOrZero((WITH dated_events AS "
                "(SELECT properties.example_date AS d FROM posthog.ai_events) SELECT d FROM dated_events))",
                0.0,
            ),
            (
                "events_scalar_cte",
                "events",
                "SELECT toFloatOrZero((WITH dated_events AS "
                "(SELECT properties.example_date AS d FROM events) SELECT d FROM dated_events))",
                0.0,
            ),
        ]
    )
    def test_datetime_property_through_projection(
        self, _name: str, table: str, query: str, expected: int | float
    ) -> None:
        PropertyDefinition.objects.create(team=self.team, name="example_date", property_type="DateTime")
        self._create_generations(table, {"example_date": "2024-04-05T06:07:08Z"})

        result = execute_hogql_query(query, team=self.team, workload=Workload.ONLINE)

        assert result.results == [(expected,)]

    @parameterized.expand(
        [
            (
                "direct",
                "SELECT properties.$ai_trace_id FROM posthog.ai_events WHERE properties.$ai_trace_id = '00123'",
            ),
            (
                "subquery",
                "SELECT trace FROM (SELECT properties.$ai_trace_id AS trace FROM posthog.ai_events) "
                "WHERE toDateTime(trace) IS NULL",
            ),
            (
                "cte",
                "WITH traces AS (SELECT properties.$ai_trace_id AS trace FROM posthog.ai_events) "
                "SELECT trace FROM traces WHERE toDateTime(trace) IS NULL",
            ),
        ]
    )
    def test_native_id_ignores_detected_numeric_type(self, _name: str, query: str) -> None:
        PropertyDefinition.objects.create(team=self.team, name="$ai_trace_id", property_type="Numeric")
        self._create_generations("posthog.ai_events", {"$ai_trace_id": "00123"})

        result = execute_hogql_query(
            query,
            team=self.team,
            workload=Workload.ONLINE,
        )

        assert result.results == [("00123",)]
