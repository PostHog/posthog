from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.helpers.timestamp_visitor import has_todate_timestamp_condition
from posthog.hogql.parser import parse_expr

from posthog.models import Team


class TestTimestampVisitor:
    def setup_method(self):
        self.context = HogQLContext(
            team_id=1,
            team=Team(pk=1, name="Test Team"),
            enable_select_queries=True,
            # database=create_hogql_database(team_id=1, database=Database.CLICKHOUSE),
            database=Database(timezone="UTC"),
            modifiers=HogQLQueryModifiers(optimizeTimestampConditions=True),
        )

    def test_has_todate_timestamp_condition_simple(self):
        expr = parse_expr("toDate(timestamp) = '2023-01-01'")
        assert has_todate_timestamp_condition(expr, self.context) is True

    def test_has_todate_timestamp_condition_false(self):
        expr = parse_expr("timestamp = '2023-01-01'")
        assert has_todate_timestamp_condition(expr, self.context) is False

    def test_has_todate_timestamp_condition_nested(self):
        expr = parse_expr("event = 'test' and toDate(timestamp) = '2023-01-01'")
        assert has_todate_timestamp_condition(expr, self.context) is True

    def test_has_todate_timestamp_condition_with_or(self):
        expr = parse_expr("event = 'test' or toDate(timestamp) = '2023-01-01'")
        assert has_todate_timestamp_condition(expr, self.context) is True

    def test_has_todate_timestamp_condition_in_function(self):
        expr = parse_expr("if(toDate(timestamp) = '2023-01-01', 1, 0)")
        assert has_todate_timestamp_condition(expr, self.context) is True

    def test_has_todate_timestamp_condition_wrong_field(self):
        expr = parse_expr("toDate(properties.some_date) = '2023-01-01'")
        assert has_todate_timestamp_condition(expr, self.context) is False

    def test_has_todate_timestamp_condition_no_args(self):
        expr = parse_expr("toDate() = '2023-01-01'")
        assert has_todate_timestamp_condition(expr, self.context) is False

    # def test_create_optimizxed_todate_condition_start_and_end(self):
    #     timestamp_field = ast.Field(chain=["timestamp"], type=DateTimeType())
    #     start_date = datetime(2023, 1, 1)
    #     end_date = datetime(2023, 1, 31)
    #     expr = create_optimized_todate_condition(timestamp_field, start_date, end_date)
    #     expected = "toDate(timestamp) >= toDate('2023-01-01') AND toDate(timestamp) <= toDate('2023-01-31')"
    #     # parsed = parse_expr(expected)
    #     # want = print_prepared_ast(parsed, self.context, "clickhouse")
    #     assert print_prepared_ast(expr, self.context, "clickhouse") == expected
    #
    # def test_create_optimized_todate_condition_start_only(self):
    #     timestamp_field = ast.Field(chain=["timestamp"], type=DateTimeType())
    #     start_date = datetime(2023, 1, 1)
    #     expr = create_optimized_todate_condition(timestamp_field, start_date=start_date)
    #     expected = "toDate(timestamp) >= toDate('2023-01-01')"
    #     assert print_ast(expr, self.context, "clickhouse") == print_ast(
    #         parse_expr(expected), self.context, "clickhouse"
    #     )
    #
    # def test_create_optimized_todate_condition_end_only(self):
    #     timestamp_field = ast.Field(chain=["timestamp"])
    #     end_date = datetime(2023, 1, 31)
    #     expr = create_optimized_todate_condition(timestamp_field, end_date=end_date)
    #     expected = "toDate(timestamp) <= toDate('2023-01-31')"
    #     assert print_ast(expr, self.context, "clickhouse") == print_ast(
    #         parse_expr(expected), self.context, "clickhouse"
    #     )
    #
    # @patch("posthog.hogql.helpers.timestamp_visitor.datetime")
    # def test_create_optimized_todate_condition_no_dates(self, mock_dt):
    #     mock_dt.now.return_value = datetime(2023, 2, 15)
    #     timestamp_field = ast.Field(chain=["timestamp"])
    #     expr = create_optimized_todate_condition(timestamp_field)
    #     expected = "toDate(timestamp) >= toDate('2023-01-16') AND toDate(timestamp) <= toDate('2023-02-15')"
    #     assert print_ast(expr, self.context, "clickhouse") == print_ast(
    #         parse_expr(expected), self.context, "clickhouse"
    #     )
