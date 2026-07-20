# Test cases for clickhouse-sql-injection rule

# ============================================
# VULNERABLE CASES - should match both rules (data is a function param AND data.get is a source)
# ============================================


def vuln_data_get(data):
    column = data.get("incremental_field")
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT max(`{column}`) FROM table")


def vuln_data_bracket(data):
    column = data["field"]
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT * FROM t WHERE col = '{column}'")


def vuln_validated_data(validated_data):
    field = validated_data.get("column_name")
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT {field} FROM table")


def vuln_request_data(request):
    field = request.data.get("field_name")
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT * FROM t WHERE col = '{field}'")


def vuln_request_data_bracket(request):
    field = request.data["field"]
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    async_execute(f"SELECT * FROM t WHERE col = '{field}'")


def vuln_request_get(request):
    table = request.GET.get("table")
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT * FROM {table}")


def vuln_request_post(request):
    col = request.POST["column"]
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT {col} FROM t")


def vuln_query_params(request):
    field = request.query_params.get("field")
    # ruleid: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT {field} FROM table")


def vuln_self_request(self):
    field = self.request.data.get("field")
    # ok: clickhouse-fstring-param-audit
    # ruleid: clickhouse-sql-injection
    sync_execute(f"SELECT {field} FROM t")


def vuln_self_request_query_params(self):
    col = self.request.query_params["col"]
    # ok: clickhouse-fstring-param-audit
    # ruleid: clickhouse-sql-injection
    execute_on_connection(f"SELECT {col} FROM t")


# ============================================
# SAFE CASES - should NOT match
# ============================================


def safe_with_escape_identifier(data):
    column = escape_clickhouse_identifier(data.get("field"))
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT max(`{column}`) FROM table")


def safe_with_escape_string(data):
    value = escape_clickhouse_string(data.get("value"))
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT * FROM t WHERE col = {value}")


def safe_hardcoded_constant():
    TABLE_NAME = "events"
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT * FROM {TABLE_NAME}")


def safe_parameterized(data):
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute("SELECT * FROM t WHERE col = %(val)s", args={"val": data.get("field")})


def safe_no_fstring(data):
    field = data.get("field")
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute("SELECT * FROM t WHERE col = %(f)s", args={"f": field})


def safe_internal_variable():
    table_name = "internal_table"
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT COUNT(*) FROM {table_name}")


def safe_loop_index():
    for i in range(10):
        # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
        sync_execute(f"SELECT * FROM t LIMIT {i}")


# ============================================
# FUNCTION PARAMETER CASES - only clickhouse-fstring-param-audit should match
# ============================================


def vuln_param_str_typed(self, column: str):
    # ok: clickhouse-sql-injection
    # ruleid: clickhouse-fstring-param-audit
    result = sync_execute(f"SELECT max(`{column}`) FROM table")
    return result


def vuln_param_untyped(self, column):
    # ok: clickhouse-sql-injection
    # ruleid: clickhouse-fstring-param-audit
    result = sync_execute(f"SELECT {column} FROM table")
    return result


def vuln_param_async(field: str):
    # ok: clickhouse-sql-injection
    # ruleid: clickhouse-fstring-param-audit
    async_execute(f"SELECT * FROM t WHERE col = '{field}'")


def safe_param_escaped(self, column: str):
    safe_col = escape_clickhouse_identifier(column)
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute(f"SELECT max(`{safe_col}`) FROM table")


def safe_param_not_in_fstring(self, column: str):
    # ok: clickhouse-sql-injection, clickhouse-fstring-param-audit
    sync_execute("SELECT * FROM t WHERE col = %(c)s", args={"c": column})
