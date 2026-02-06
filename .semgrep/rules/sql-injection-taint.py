from psycopg2 import sql
from posthog.hogql.escape_sql import escape_clickhouse_identifier

# === sql-injection-user-input: SHOULD BE CAUGHT (ruleid) ===


def bad_format_string(request, cursor):
    user_id = request.GET.get("user_id")
    # ruleid: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = {}".format(user_id))


def bad_percent_format(request, cursor):
    user_id = request.GET.get("user_id")
    # ruleid: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)


def bad_string_concat(request, cursor):
    user_id = request.GET.get("user_id")
    # ruleid: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = " + user_id)


def bad_model_raw_format(request, Model):
    user_id = request.GET.get("user_id")
    # ruleid: sql-injection-user-input
    Model.raw("SELECT * FROM users WHERE id = {}".format(user_id))


def bad_model_raw_percent(request, Model):
    user_id = request.POST.get("user_id")
    # ruleid: sql-injection-user-input
    Model.raw("SELECT * FROM users WHERE id = %s" % user_id)


def bad_data_param(request, cursor):
    value = request.data.get("value")
    # ruleid: sql-injection-user-input
    cursor.execute("UPDATE users SET score = {}".format(value))


def bad_query_params(request, cursor):
    team_id = request.query_params.get("team_id")
    # ruleid: sql-injection-user-input
    cursor.execute("SELECT * FROM events WHERE team_id = {}".format(team_id))


def bad_bracket_access(request, cursor):
    user_id = request.GET["user_id"]
    # ruleid: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = {}".format(user_id))


def bad_serializer_data(serializer, cursor):
    user_id = serializer.validated_data.get("user_id")
    # ruleid: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = {}".format(user_id))


# === sql-injection-user-input: SHOULD NOT BE CAUGHT (ok) ===


def safe_parameterized_query(request, cursor):
    user_id = request.GET.get("user_id")
    # ok: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = %s", [user_id])


def safe_parameterized_dict(request, cursor):
    user_id = request.GET.get("user_id")
    # ok: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = %(user_id)s", {"user_id": user_id})


def safe_int_cast(request, cursor):
    user_id = int(request.GET.get("user_id"))
    # ok: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE id = {}".format(user_id))


def safe_escape_identifier(request, cursor):
    table_name = request.GET.get("table")
    safe_table = escape_clickhouse_identifier(table_name)
    # ok: sql-injection-user-input
    cursor.execute("SELECT * FROM {} WHERE active = true".format(safe_table))


def safe_psycopg2_identifier(request, cursor):
    table_name = request.GET.get("table")
    query = sql.SQL("SELECT * FROM {} WHERE active = true").format(
        sql.Identifier(table_name)
    )
    # ok: sql-injection-user-input
    cursor.execute(query)


def safe_orm_metadata(cursor, model, user_id):
    # Table name from Django ORM metadata is trusted
    table = model._meta.db_table
    # ok: sql-injection-user-input
    cursor.execute("SELECT COUNT(*) FROM {} WHERE id = %s".format(table), [user_id])


def safe_no_user_input(cursor):
    # ok: sql-injection-user-input
    cursor.execute("SELECT * FROM users WHERE active = true")


def safe_hardcoded_values(cursor):
    limit = 100
    # ok: sql-injection-user-input
    cursor.execute("SELECT * FROM users LIMIT {}".format(limit))


def safe_fstring_no_taint(cursor, user_id):
    # f-strings without user input source are not caught by taint rule
    # ok: sql-injection-user-input
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
