from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_select


# ============================================================================
# hogql-injection-taint: SHOULD FIND (user data interpolated into f-strings)
# ============================================================================


class TestTaintVulnerable:
    def test_query_field_in_fstring(self):
        # ruleid: hogql-injection-taint, hogql-fstring-audit
        parse_expr(f"field = {self.query.someField}")

    def test_query_field_in_fstring_to_select(self):
        # ruleid: hogql-injection-taint, hogql-fstring-audit
        parse_select(f"SELECT * WHERE {self.query.filter}")

    def test_query_field_in_fstring_to_order(self):
        # ruleid: hogql-injection-taint, hogql-fstring-audit
        parse_order_expr(f"{self.query.orderBy} DESC")

    def test_context_in_fstring_loop(self):
        for prop in self.context.includeProperties:
            # ruleid: hogql-injection-taint, hogql-fstring-audit
            parse_expr(f"has({prop})")

    def test_series_math_in_fstring(self):
        # ruleid: hogql-injection-taint, hogql-fstring-audit
        parse_expr(f"SELECT {self.series.math_hogql}")

    def test_indirect_fstring_flow(self):
        query = f"field = {self.query.expression}"
        # ruleid: hogql-injection-taint
        parse_expr(query)


# ============================================================================
# hogql-injection-taint: SHOULD NOT FIND (safe patterns)
# ============================================================================


class TestTaintSafe:
    def test_entire_expression_direct(self):
        # Safe: user provides entire HogQL expression (no context to escape)
        # ok: hogql-injection-taint
        parse_expr(self.query.someField)

    def test_entire_expression_select(self):
        # ok: hogql-injection-taint
        parse_select(self.query.queryString)

    def test_entire_expression_order(self):
        # ok: hogql-injection-taint
        parse_order_expr(self.query.orderBy)

    def test_loop_variable_direct(self):
        for prop in self.context.includeProperties:
            # ok: hogql-injection-taint
            parse_expr(prop)

    def test_series_math_direct(self):
        # ok: hogql-injection-taint
        parse_expr(self.series.math_hogql)

    def test_indirect_flow_no_fstring(self):
        x = self.query.expression
        # ok: hogql-injection-taint
        parse_expr(x)

    def test_sanitized_with_ast_constant(self):
        value = self.query.someField
        # ok: hogql-injection-taint
        parse_expr("{x}", placeholders={"x": ast.Constant(value=value)})

    def test_sanitized_with_ast_tuple(self):
        values = self.query.values
        # ok: hogql-injection-taint
        parse_expr("{x}", placeholders={"x": ast.Tuple(exprs=[ast.Constant(value=v) for v in values])})

    def test_hardcoded_string(self):
        # ok: hogql-injection-taint
        parse_expr("count(*)")

    def test_no_taint_source(self):
        x = "some_column"
        # ok: hogql-injection-taint
        parse_expr(x)

    def test_fstring_no_user_data(self):
        i = 5
        # ok: hogql-injection-taint
        parse_expr(f"step_{i}")


# ============================================================================
# hogql-fstring-audit: SHOULD FIND (vulnerable patterns)
# ============================================================================


class TestFstringVulnerable:
    def test_unknown_var_parse_expr(self):
        dangerous = get_user_input()
        # ruleid: hogql-fstring-audit
        parse_expr(f"SELECT {dangerous}")

    def test_unknown_var_parse_select(self):
        user_query = request.args.get("q")
        # ruleid: hogql-fstring-audit
        parse_select(f"SELECT * FROM events WHERE {user_query}")

    def test_unknown_var_parse_order(self):
        sort_col = params["sort"]
        # ruleid: hogql-fstring-audit
        parse_order_expr(f"{sort_col} DESC")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Step/Latest/Exclusion prefixes
# ============================================================================


class TestFstringSafeStepPatterns:
    def test_step_prefix(self):
        i = 0
        # ok: hogql-fstring-audit
        parse_expr(f"step_{i}_value")

    def test_latest_prefix(self):
        i = 1
        # ok: hogql-fstring-audit
        parse_expr(f"latest_{i}")

    def test_exclusion_prefix(self):
        i = 2
        # ok: hogql-fstring-audit
        parse_expr(f"exclusion_{i}_condition")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - .pk and table_alias
# ============================================================================


class TestFstringSafePkAndAlias:
    def test_pk_suffix(self):
        obj = some_object
        # ok: hogql-fstring-audit
        parse_expr(f"id = {obj.pk}")

    def test_table_alias(self):
        table_alias = "e"
        # ok: hogql-fstring-audit
        parse_expr(f"{table_alias}.timestamp")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Loop indices {i}, {index}
# ============================================================================


class TestFstringSafeLoopIndices:
    def test_i_variable(self):
        for i in range(10):
            # ok: hogql-fstring-audit
            parse_expr(f"col_{i}")

    def test_index_variable(self):
        index = 5
        # ok: hogql-fstring-audit
        parse_expr(f"arr[{index}]")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Funnel step integers
# ============================================================================


class TestFstringSafeFunnelSteps:
    def test_target_step(self):
        target_step = self.context.max_steps
        # ok: hogql-fstring-audit
        parse_expr(f"{target_step} AS target")

    def test_max_steps(self):
        max_steps = 5
        # ok: hogql-fstring-audit
        parse_expr(f"steps <= {max_steps}")

    def test_step_num(self):
        step_num = 3
        # ok: hogql-fstring-audit
        parse_expr(f"step = {step_num}")

    def test_funnelStep(self):
        funnelStep = 2
        # ok: hogql-fstring-audit
        parse_expr(f"bitTest(flags, {funnelStep})")

    def test_from_step(self):
        from_step = 1
        # ok: hogql-fstring-audit
        parse_expr(f"arraySlice(arr, {from_step})")

    def test_to_step(self):
        to_step = 3
        # ok: hogql-fstring-audit
        parse_expr(f"arraySlice(arr, 1, {to_step})")

    def test_absolute_actors_step(self):
        absolute_actors_step = 2
        # ok: hogql-fstring-audit
        parse_expr(f"events[{absolute_actors_step}]")

    def test_bin_count(self):
        bin_count = 10
        # ok: hogql-fstring-audit
        parse_expr(f"histogram({bin_count})")

    def test_first_step(self):
        first_step = 0
        # ok: hogql-fstring-audit
        parse_expr(f"events[{first_step}]")

    def test_final_step(self):
        final_step = 5
        # ok: hogql-fstring-audit
        parse_expr(f"events[{final_step}]")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Array indexing [{var}]
# ============================================================================


class TestFstringSafeArrayIndexing:
    def test_simple_index(self):
        step = 1
        # ok: hogql-fstring-audit
        parse_expr(f"matched_events[{step}]")

    def test_index_with_addition(self):
        step = 1
        # ok: hogql-fstring-audit
        parse_expr(f"events[{step + 1}]")

    def test_index_with_subtraction(self):
        idx = 5
        # ok: hogql-fstring-audit
        parse_expr(f"arr[{idx - 1}]")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Internal constants
# ============================================================================


class TestFstringSafeConstants:
    def test_order_dir(self):
        order_dir = "ASC"
        # ok: hogql-fstring-audit
        parse_order_expr(f"timestamp {order_dir}")

    def test_order_clause(self):
        order_clause = "rand()"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * ORDER BY {order_clause}")

    def test_actor(self):
        actor = "e.person_id"
        # ok: hogql-fstring-audit
        parse_expr(f"count(DISTINCT {actor})")

    def test_field(self):
        field = "created_at"
        # ok: hogql-fstring-audit
        parse_expr(f"toStartOfMonth({field})")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Computed SQL fragments
# ============================================================================


class TestFstringSafeComputedFragments:
    def test_statement(self):
        statement = "if(cond, a, b)"
        # ok: hogql-fstring-audit
        parse_expr(f"{statement} as result")

    def test_event_clause(self):
        event_clause = "event = 'click'"
        # ok: hogql-fstring-audit
        parse_expr(f"{event_clause}")

    def test_prop_selector(self):
        prop_selector = "properties.name"
        # ok: hogql-fstring-audit
        parse_expr(f"{prop_selector}")

    def test_prop_vals(self):
        prop_vals = "['a', 'b']"
        # ok: hogql-fstring-audit
        parse_expr(f"{prop_vals}")

    def test_conversion_filter(self):
        conversion_filter = "timestamp > now()"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * WHERE {conversion_filter}")

    def test_event_join_query(self):
        event_join_query = "JOIN events ON id = event_id"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * FROM foo {event_join_query}")

    def test_recording_event_select_statement(self):
        recording_event_select_statement = ", events.uuid"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT id {recording_event_select_statement}")

    def test_funnel_step_names(self):
        funnel_step_names = "['step1', 'step2']"
        # ok: hogql-fstring-audit
        parse_expr(f"{funnel_step_names} AS names")

    def test_percentile_function(self):
        percentile_function = "quantile(0.95)"
        # ok: hogql-fstring-audit
        parse_expr(f"{percentile_function}(value)")

    def test_metric_value_field(self):
        metric_value_field = "properties.value"
        # ok: hogql-fstring-audit
        parse_expr(f"{metric_value_field}")

    def test_default_breakdown_selector(self):
        default_breakdown_selector = "breakdown_value"
        # ok: hogql-fstring-audit
        parse_expr(f"{default_breakdown_selector}")

    def test_where_clause(self):
        where_clause = "event = 'click'"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * WHERE {where_clause}")

    def test_array_join_query(self):
        array_join_query = "ARRAY JOIN props"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * {array_join_query}")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Funnel computed values
# ============================================================================


class TestFstringSafeFunnelComputed:
    def test_step_results(self):
        step_results = "count() as step_1"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {step_results}")

    def test_conversion_time_arrays(self):
        conversion_time_arrays = "groupArray(time)"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {conversion_time_arrays}")

    def test_final_prop(self):
        final_prop = "breakdown"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {final_prop}")

    def test_order_by(self):
        order_by = "step_1 DESC"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * ORDER BY {order_by}")

    def test_mean_conversion_times(self):
        mean_conversion_times = "avg(time)"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {mean_conversion_times}")

    def test_median_conversion_times(self):
        median_conversion_times = "median(time)"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {median_conversion_times}")

    def test_conversion_rate_expr(self):
        conversion_rate_expr = "count() / total"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {conversion_rate_expr}")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Interval/time patterns
# ============================================================================


class TestFstringSafeIntervals:
    def test_interval(self):
        interval = 7
        # ok: hogql-fstring-audit
        parse_expr(f"INTERVAL {interval} DAY")

    def test_interval_unit(self):
        interval_unit = "DAY"
        # ok: hogql-fstring-audit
        parse_expr(f"INTERVAL 1 {interval_unit}")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Method calls
# ============================================================================


class TestFstringSafeMethodCalls:
    def test_get_breakdown(self):
        # ok: hogql-fstring-audit
        parse_expr(f"PARTITION BY {self._get_breakdown_prop()}")

    def test_timezone_wrapper(self):
        # ok: hogql-fstring-audit
        parse_expr(f"WHERE {timezone_wrapper('timestamp')} > now()")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - int() conversion
# ============================================================================


class TestFstringSafeIntConversion:
    def test_int_self(self):
        # ok: hogql-fstring-audit
        parse_expr(f'count(DISTINCT e."$group_{int(self.series.math_group_type_index)}")')


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Limit/offset/count
# ============================================================================


class TestFstringSafeLimits:
    def test_limit(self):
        limit = 100
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * LIMIT {limit}")

    def test_offset(self):
        offset = 50
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * OFFSET {offset}")

    def test_count(self):
        count = 10
        # ok: hogql-fstring-audit
        parse_expr(f"groupArray({count})")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Computed expressions
# ============================================================================


class TestFstringSafeComputedExpressions:
    def test_timestamp_expr(self):
        timestamp_expr = "toDateTime(ts)"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {timestamp_expr}")

    def test_array_merge_operation(self):
        array_merge_operation = "arraySum(arr)"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {array_merge_operation}")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Date filter patterns
# ============================================================================


class TestFstringSafeDateFilters:
    def test_date_to_filter(self):
        date_to_filter = "toDateTime('2024-01-01')"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * WHERE ts <= {date_to_filter}")

    def test_date_from_filter(self):
        date_from_filter = "toDateTime('2023-01-01')"
        # ok: hogql-fstring-audit
        parse_select(f"SELECT * WHERE ts >= {date_from_filter}")


# ============================================================================
# hogql-fstring-audit: SHOULD NOT FIND - Inline ternary
# ============================================================================


class TestFstringSafeTernary:
    def test_inline_ternary(self):
        is_cumulative = True
        # ok: hogql-fstring-audit
        parse_select(f"SELECT {'total' if is_cumulative else 'count'}")

    def test_ternary_with_quotes(self):
        ascending = False
        # ok: hogql-fstring-audit
        parse_order_expr(f"timestamp {'ASC' if ascending else 'DESC'}")


# ============================================================================
# clickhouse-injection-taint: SHOULD FIND (user data in f-strings to execute)
# ============================================================================


class TestClickhouseTaintVulnerable:
    def test_self_field_in_fstring(self):
        # ruleid: clickhouse-injection-taint
        sync_execute(f"SELECT max(`{self.column}`) FROM events")

    def test_self_query_field_in_fstring(self):
        # ruleid: clickhouse-injection-taint
        sync_execute(f"SELECT * FROM {self.query.table_name}")

    def test_indirect_fstring_flow(self):
        query = f"SELECT * FROM {self.table_name}"
        # ruleid: clickhouse-injection-taint
        sync_execute(query)


def test_method_param_in_fstring(column: str):
    # Method parameter used in f-string - not tracked by taint rule (too many false positives)
    # ok: clickhouse-injection-taint
    sync_execute(f"SELECT max(`{column}`) FROM events")


def test_method_param_escaped(column: str):
    # Method parameter escaped - safe
    safe_col = escape_clickhouse_identifier(column)
    # ok: clickhouse-injection-taint
    sync_execute(f"SELECT max({safe_col}) FROM events")


# ============================================================================
# clickhouse-injection-taint: SHOULD NOT FIND (safe patterns)
# ============================================================================


class TestClickhouseTaintSafe:
    def test_escaped_identifier(self):
        safe_col = escape_clickhouse_identifier(self.column)
        # ok: clickhouse-injection-taint
        sync_execute(f"SELECT {safe_col} FROM events")

    def test_constant_table(self):
        # ok: clickhouse-injection-taint
        sync_execute(f"SELECT * FROM {EVENTS_TABLE}")

    def test_parameterized_values(self):
        # ok: clickhouse-injection-taint
        sync_execute("SELECT * FROM events WHERE id = %(id)s", {"id": self.query.id})

    def test_no_fstring(self):
        # ok: clickhouse-injection-taint
        sync_execute("SELECT * FROM events")
