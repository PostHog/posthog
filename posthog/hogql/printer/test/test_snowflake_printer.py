"""Tests for printing HogQL to the Snowflake dialect."""

from typing import Optional, cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast, prepare_ast_for_printing, print_prepared_ast

SNOWFLAKE_EMIT_CASES: list[tuple[str, str, str]] = [
    # Casts (Snowflake type synonyms; no UUID type → VARCHAR)
    ("toString", "toString(1)", "CAST(1 AS VARCHAR)"),
    ("toFloat", "toFloat('1.5')", "CAST(%(hogql_val_0)s AS DOUBLE)"),
    ("toUUID", "toUUID('x')", "CAST(%(hogql_val_0)s AS VARCHAR)"),
    ("toDate", "toDate(now())", "CAST(CURRENT_TIMESTAMP() AS DATE)"),
    # Date extraction (Snowflake EXTRACT unit names)
    ("toYear", "toYear(now())", "EXTRACT(YEAR FROM CURRENT_TIMESTAMP())"),
    ("toDayOfWeek", "toDayOfWeek(now())", "EXTRACT(dayofweekiso FROM CURRENT_TIMESTAMP())"),
    ("toDayOfYear", "toDayOfYear(now())", "EXTRACT(dayofyear FROM CURRENT_TIMESTAMP())"),
    ("toISOWeek", "toISOWeek(now())", "EXTRACT(weekiso FROM CURRENT_TIMESTAMP())"),
    ("toISOYear", "toISOYear(now())", "EXTRACT(yearofweekiso FROM CURRENT_TIMESTAMP())"),
    ("toUnixTimestamp", "toUnixTimestamp(now())", "CAST(DATE_PART('epoch_second', CURRENT_TIMESTAMP()) AS BIGINT)"),
    ("toYYYYMMDD", "toYYYYMMDD(now())", "CAST(TO_CHAR(CURRENT_TIMESTAMP(), 'YYYYMMDD') AS INTEGER)"),
    # Date truncation / generators
    ("toMonday", "toMonday(now())", "CAST(DATE_TRUNC('week', CURRENT_TIMESTAMP()) AS DATE)"),
    ("toLastDayOfMonth", "toLastDayOfMonth(now())", "CAST(LAST_DAY(CURRENT_TIMESTAMP()) AS DATE)"),
    ("today", "today()", "CURRENT_DATE"),
    ("yesterday", "yesterday()", "(CURRENT_DATE - INTERVAL '1 day')"),
    # toStartOf* (DATE_TRUNC; week/ISO-year via DAYOFWEEKISO so WEEK_START is irrelevant;
    # sub-hour buckets via native TIME_SLICE)
    ("toStartOfDay", "toStartOfDay(now())", "DATE_TRUNC('day', CURRENT_TIMESTAMP())"),
    ("toStartOfMonth", "toStartOfMonth(now())", "DATE_TRUNC('month', CURRENT_TIMESTAMP())"),
    ("toStartOfHour", "toStartOfHour(now())", "DATE_TRUNC('hour', CURRENT_TIMESTAMP())"),
    ("toStartOfQuarter", "toStartOfQuarter(now())", "DATE_TRUNC('quarter', CURRENT_TIMESTAMP())"),
    (
        "toStartOfWeek",
        "toStartOfWeek(now())",
        "DATE_TRUNC('day', DATEADD('day', -(DAYOFWEEKISO(CURRENT_TIMESTAMP()) % 7), CURRENT_TIMESTAMP()))",
    ),
    (
        "toStartOfISOYear",
        "toStartOfISOYear(now())",
        "DATEADD('day', 1 - DAYOFWEEKISO(DATE_FROM_PARTS(YEAROFWEEKISO(CURRENT_TIMESTAMP()), 1, 4)), "
        "DATE_FROM_PARTS(YEAROFWEEKISO(CURRENT_TIMESTAMP()), 1, 4))",
    ),
    ("toStartOfFiveMinutes", "toStartOfFiveMinutes(now())", "TIME_SLICE(CURRENT_TIMESTAMP(), 5, 'MINUTE')"),
    (
        "toStartOfFifteenMinutes",
        "toStartOfFifteenMinutes(now())",
        "TIME_SLICE(CURRENT_TIMESTAMP(), 15, 'MINUTE')",
    ),
    # Intervals / arithmetic (DATEADD; no INTERVAL multiplication)
    ("toIntervalDay", "toIntervalDay(7)", "INTERVAL '7 day'"),
    ("addDays", "addDays(now(), 7)", "DATEADD('day', 7, CURRENT_TIMESTAMP())"),
    ("subtractMonths", "subtractMonths(now(), 3)", "DATEADD('month', -(3), CURRENT_TIMESTAMP())"),
    # dateDiff / formatDateTime — unit / format inlined as a literal
    ("dateDiff", "dateDiff('day', now(), now())", "DATEDIFF('day', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())"),
    (
        "formatDateTime",
        "formatDateTime(now(), '%Y-%m-%d %H:%M:%S')",
        "TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI:SS')",
    ),
    # A literal double-quote is escaped as "" inside the quoted run, not dropped.
    (
        "formatDateTime_escapes_literal_quote",
        "formatDateTime(now(), '%Y\"q\"')",
        'TO_CHAR(CURRENT_TIMESTAMP(), \'YYYY"""q"""\')',
    ),
    (
        "formatDateTime_escapes_lone_quote",
        "formatDateTime(now(), '%H\"%M')",
        'TO_CHAR(CURRENT_TIMESTAMP(), \'HH24""""MI\')',
    ),
    # A literal single-quote (escaped `''` in HogQL) must be re-escaped as `''` so it can't close
    # the surrounding SQL string literal — guards the formatDateTime injection vector.
    (
        "formatDateTime_escapes_single_quote",
        "formatDateTime(now(), '%Y''T''%H')",
        "TO_CHAR(CURRENT_TIMESTAMP(), 'YYYY\"''T''\"HH24')",
    ),
    # Conditional / null
    ("if", "if(1, 2, 3)", "CASE WHEN 1 THEN 2 ELSE 3 END"),
    (
        "simple_case",
        "CASE event WHEN '$pageview' THEN event ELSE '' END",
        'CASE events."event" WHEN %(hogql_val_0)s THEN events."event" ELSE %(hogql_val_1)s END',
    ),
    ("isNull", "isNull(1)", "(1 IS NULL)"),
    # Regex operators → REGEXP_INSTR (match()-style "found anywhere"); 'i' = case-insensitive
    ("regex_match", "'h' =~ 'h.*o'", "(REGEXP_INSTR(%(hogql_val_0)s, %(hogql_val_1)s) != 0)"),
    ("regex_not_match", "'h' !~ 'h.*o'", "(REGEXP_INSTR(%(hogql_val_0)s, %(hogql_val_1)s) = 0)"),
    ("regex_imatch", "'h' =~* 'h.*o'", "(REGEXP_INSTR(%(hogql_val_0)s, %(hogql_val_1)s, 1, 1, 0, 'i') != 0)"),
    ("regex_not_imatch", "'h' !~* 'h.*o'", "(REGEXP_INSTR(%(hogql_val_0)s, %(hogql_val_1)s, 1, 1, 0, 'i') = 0)"),
    # `::` casts map HogQL type names to Snowflake types (consistent with toString/toInt/...)
    ("cast_string", "1::String", "CAST(1 AS VARCHAR)"),
    ("cast_int", "1.5::Int", "CAST(1.5 AS BIGINT)"),
    ("cast_bool", "1::Bool", "CAST(1 AS BOOLEAN)"),
    # Array / object literals → constructors
    ("array_literal", "[1, 2, 3]", "ARRAY_CONSTRUCT(1, 2, 3)"),
    ("object_literal", "{'a': 1}", "OBJECT_CONSTRUCT(%(hogql_val_0)s, 1)"),
    # JSON (PARSE_JSON + bracket path; chained keys for nested access)
    (
        "JSONExtractString",
        "JSONExtractString('{}', 'a')",
        "CAST(PARSE_JSON(%(hogql_val_0)s)[%(hogql_val_1)s] AS VARCHAR)",
    ),
    (
        "JSONExtractInt_nested",
        "JSONExtractInt('{}', 'a', 'b')",
        "CAST(PARSE_JSON(%(hogql_val_0)s)[%(hogql_val_1)s][%(hogql_val_2)s] AS INTEGER)",
    ),
    ("JSONExtractRaw", "JSONExtractRaw('{}', 'a')", "PARSE_JSON(%(hogql_val_0)s)[%(hogql_val_1)s]"),
    ("JSONLength", "JSONLength('[]')", "ARRAY_SIZE(PARSE_JSON(%(hogql_val_0)s))"),
    # String
    ("match", "match('h', 'h.*o')", "(REGEXP_INSTR(%(hogql_val_0)s, %(hogql_val_1)s) != 0)"),
    ("splitByChar", "splitByChar(',', 'a,b')", "SPLIT(%(hogql_val_1)s, %(hogql_val_0)s)"),
    (
        "replaceOne",
        "replaceOne('a', 'b', 'c')",
        "REGEXP_REPLACE(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s, 1, 1)",
    ),
    # Math
    ("log10", "log10(100)", "LOG(10, 100)"),
    ("log", "log(2)", "LN(2)"),
    ("rand", "rand()", "UNIFORM(0::float, 1::float, RANDOM())"),
    # Aggregation (no FILTER clause; CASE WHEN / COUNT_IF)
    ("countIf_1arg", "countIf(1)", "COUNT_IF(1)"),
    ("countIf_2arg", "countIf(event, 1)", 'COUNT(CASE WHEN 1 THEN events."event" END)'),
    ("sumIf", "sumIf(1, 1)", "SUM(CASE WHEN 1 THEN 1 END)"),
    ("avgIf", "avgIf(1, 1)", "AVG(CASE WHEN 1 THEN 1 END)"),
    ("anyIf", "anyIf(1, 1)", "MIN(CASE WHEN 1 THEN 1 END)"),
    ("groupArrayIf", "groupArrayIf(1, 1)", "ARRAY_AGG(CASE WHEN 1 THEN 1 END)"),
    ("uniqIf", "uniqIf(1, 1)", "COUNT(DISTINCT CASE WHEN 1 THEN 1 END)"),
    ("uniq", "uniq(1)", "COUNT(DISTINCT 1)"),
    # Renames
    ("ifNull", "ifNull(1, 2)", "COALESCE(1, 2)"),
    ("groupArray", "groupArray(event)", 'ARRAY_AGG(events."event")'),
    ("toTypeName", "toTypeName(1)", "TYPEOF(1)"),
    ("startsWith", "startsWith('a', 'b')", "STARTSWITH(%(hogql_val_0)s, %(hogql_val_1)s)"),
    ("now", "now()", "CURRENT_TIMESTAMP()"),
    ("pow", "pow(2, 3)", "POWER(2, 3)"),
    # count() means "count all rows"; Snowflake rejects a bare COUNT(), so emit COUNT(*).
    ("count_star", "count()", "count(*)"),
    ("count_expr", "count(event)", 'count(events."event")'),
    # Snowflake supports COUNT(DISTINCT expr) — the count handler must honor the distinct flag.
    ("count_distinct", "count(distinct event)", 'count(DISTINCT events."event")'),
    # Passthrough (valid Snowflake verbatim)
    ("avg", "avg(1)", "avg(1)"),
    ("coalesce", "coalesce(1, 2)", "coalesce(1, 2)"),
    ("power", "power(2, 3)", "power(2, 3)"),
]


class TestSnowflakePrinter(BaseTest):
    maxDiff = None

    def _expr(
        self,
        query: ast.Expr | str,
        context: Optional[HogQLContext] = None,
    ) -> str:
        node = parse_expr(query, backend="cpp-json") if isinstance(query, str) else query
        context = context or HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        select_query = ast.SelectQuery(select=[node], select_from=ast.JoinExpr(table=ast.Field(chain=["events"])))
        prepared_select_query: ast.SelectQuery = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(select_query, context=context, dialect="snowflake", stack=[select_query]),
        )
        return print_prepared_ast(
            prepared_select_query.select[0],
            context=context,
            dialect="snowflake",
            stack=[prepared_select_query],
        )

    @parameterized.expand(SNOWFLAKE_EMIT_CASES)
    def test_snowflake_emit(self, _name: str, hogql_expr: str, expected: str):
        self.assertEqual(self._expr(hogql_expr), expected)

    @parameterized.expand(
        [
            ("datediff_non_literal_unit", "dateDiff(event, now(), now())", "requires a literal unit"),
            ("datediff_bad_unit", "dateDiff('fortnight', now(), now())", "Unsupported dateDiff unit 'fortnight'"),
            (
                "format_unknown_specifier",
                "formatDateTime(now(), '%Q')",
                "Unsupported formatDateTime specifier '%Q'",
            ),
            ("unsupported_function", "argMax(1, 2)", "not supported in the Snowflake dialect"),
            # Tier 0: constructs with no safe Snowflake equivalent reject loudly
            ("tuple", "(1, 2)", "Tuple expressions are not supported"),
            ("array_slice", "[1, 2, 3][1:2]", "Array slices are not"),
            ("unsupported_cast", "1::Nonsense", "Unsupported cast to type 'nonsense'"),
        ]
    )
    def test_snowflake_errors(self, _name: str, hogql_expr: str, error_substring: str):
        with self.assertRaises(QueryError) as ctx:
            self._expr(hogql_expr)
        self.assertIn(error_substring, str(ctx.exception))

    def _select(self, query: str) -> str:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        return prepare_and_print_ast(parse_select(query, backend="cpp-json"), context, "snowflake")[0]

    @parameterized.expand(
        [
            ("array_join", "SELECT x FROM events ARRAY JOIN [1, 2] AS x", "ARRAY JOIN is not supported"),
            ("prewhere", "SELECT event FROM events PREWHERE event = 'x'", "PREWHERE is not supported"),
            ("sample", "SELECT event FROM events SAMPLE 0.1", "SAMPLE is not supported"),
            ("limit_by", "SELECT event FROM events LIMIT 1 BY event", "LIMIT BY is not supported"),
        ]
    )
    def test_snowflake_clause_errors(self, _name: str, query: str, error_substring: str):
        with self.assertRaises(QueryError) as ctx:
            self._select(query)
        self.assertIn(error_substring, str(ctx.exception))

    def test_snowflake_qualify_emits_natively(self):
        # QUALIFY parses and resolves but the base/HogQL printers rejected it; Snowflake supports
        # it natively, so it should print straight through.
        sql = self._select("SELECT event FROM events QUALIFY row_number() OVER (ORDER BY timestamp) = 1")
        self.assertIn("QUALIFY", sql)

    def test_snowflake_pivot_emits_unqualified_columns_and_star_projection(self):
        # Snowflake rejects table-qualified columns inside PIVOT, and its output columns are named
        # after the IN values (which HogQL can't enumerate) — so the projection stays `*`.
        sql = self._select("SELECT * FROM events PIVOT(count(timestamp) FOR event IN ('pageview', 'click'))")
        self.assertIn('PIVOT (count("timestamp") FOR "event" IN (', sql)
        self.assertTrue(sql.startswith("SELECT * FROM events PIVOT ("), sql)

    def test_snowflake_unpivot_emits_unqualified_columns(self):
        sql = self._select("SELECT * FROM (SELECT 1 AS jan, 2 AS feb) AS t UNPIVOT(amount FOR month IN (jan, feb))")
        self.assertIn('UNPIVOT ("amount" FOR "month" IN ("jan", "feb"))', sql)

    def test_snowflake_pivot_rejects_inner_group_by(self):
        with self.assertRaises(QueryError):
            self._select("SELECT * FROM events PIVOT(count(timestamp) FOR event IN ('a') GROUP BY uuid)")
