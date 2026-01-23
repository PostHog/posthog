# Test cases for clickhouse-sql-injection rule

# ============================================
# VULNERABLE CASES - should match
# ============================================


# ruleid: clickhouse-sql-injection
def vuln_data_get(data):
    column = data.get("incremental_field")
    sync_execute(f"SELECT max(`{column}`) FROM table")


# ruleid: clickhouse-sql-injection
def vuln_data_bracket(data):
    column = data["field"]
    sync_execute(f"SELECT * FROM t WHERE col = '{column}'")


# ruleid: clickhouse-sql-injection
def vuln_validated_data(validated_data):
    field = validated_data.get("column_name")
    sync_execute(f"SELECT {field} FROM table")


# ruleid: clickhouse-sql-injection
def vuln_request_data(request):
    field = request.data.get("field_name")
    sync_execute(f"SELECT * FROM t WHERE col = '{field}'")


# ruleid: clickhouse-sql-injection
def vuln_request_data_bracket(request):
    field = request.data["field"]
    async_execute(f"SELECT * FROM t WHERE col = '{field}'")


# ruleid: clickhouse-sql-injection
def vuln_request_get(request):
    table = request.GET.get("table")
    sync_execute(f"SELECT * FROM {table}")


# ruleid: clickhouse-sql-injection
def vuln_request_post(request):
    col = request.POST["column"]
    sync_execute(f"SELECT {col} FROM t")


# ruleid: clickhouse-sql-injection
def vuln_query_params(request):
    field = request.query_params.get("field")
    sync_execute(f"SELECT {field} FROM table")


# ruleid: clickhouse-sql-injection
def vuln_self_request(self):
    field = self.request.data.get("field")
    sync_execute(f"SELECT {field} FROM t")


# ruleid: clickhouse-sql-injection
def vuln_self_request_query_params(self):
    col = self.request.query_params["col"]
    execute_on_connection(f"SELECT {col} FROM t")


# ============================================
# SAFE CASES - should NOT match
# ============================================


# ok: clickhouse-sql-injection
def safe_with_escape_identifier(data):
    column = escape_clickhouse_identifier(data.get("field"))
    sync_execute(f"SELECT max(`{column}`) FROM table")


# ok: clickhouse-sql-injection
def safe_with_escape_string(data):
    value = escape_clickhouse_string(data.get("value"))
    sync_execute(f"SELECT * FROM t WHERE col = {value}")


# ok: clickhouse-sql-injection
def safe_hardcoded_constant():
    TABLE_NAME = "events"
    sync_execute(f"SELECT * FROM {TABLE_NAME}")


# ok: clickhouse-sql-injection
def safe_parameterized(data):
    sync_execute("SELECT * FROM t WHERE col = %(val)s", args={"val": data.get("field")})


# ok: clickhouse-sql-injection
def safe_no_fstring(data):
    field = data.get("field")
    sync_execute("SELECT * FROM t WHERE col = %(f)s", args={"f": field})


# ok: clickhouse-sql-injection
def safe_internal_variable():
    table_name = "internal_table"
    sync_execute(f"SELECT COUNT(*) FROM {table_name}")


# ok: clickhouse-sql-injection
def safe_loop_index():
    for i in range(10):
        sync_execute(f"SELECT * FROM t LIMIT {i}")


# ============================================
# FUNCTION PARAMETER CASES - for clickhouse-fstring-param-audit rule
# ============================================


# ruleid: clickhouse-fstring-param-audit
def vuln_param_str_typed(self, column: str):
    result = sync_execute(f"SELECT max(`{column}`) FROM table")
    return result


# ruleid: clickhouse-fstring-param-audit
def vuln_param_untyped(self, column):
    result = sync_execute(f"SELECT {column} FROM table")
    return result


# ruleid: clickhouse-fstring-param-audit
def vuln_param_async(field: str):
    async_execute(f"SELECT * FROM t WHERE col = '{field}'")


# ok: clickhouse-fstring-param-audit
def safe_param_escaped(self, column: str):
    safe_col = escape_clickhouse_identifier(column)
    sync_execute(f"SELECT max(`{safe_col}`) FROM table")


# ok: clickhouse-fstring-param-audit
def safe_param_not_in_fstring(self, column: str):
    sync_execute("SELECT * FROM t WHERE col = %(c)s", args={"c": column})
