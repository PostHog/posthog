from functools import cache
from typing import Optional

from django.conf import settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier

from posthog.person_db_router import PERSONS_DB_MODELS
from posthog.scopes import APIScopeObject


@cache
def _pk_column_for_pg_table(postgres_table_name: str) -> str:
    from django.apps import apps

    for model in apps.get_models():
        if model._meta.db_table == postgres_table_name:
            return model._meta.pk.column
    return "id"


def build_function_call(postgres_table_name: str, context: Optional[HogQLContext] = None):
    raw_params: dict[str, str] = {}

    def add_param(value: str, is_sensitive: bool = True) -> str:
        if context is not None:
            if is_sensitive:
                return context.add_sensitive_value(value)
            return context.add_value(value)

        param_name = f"value_{len(raw_params.items())}"
        raw_params[param_name] = value
        return f"%({param_name})s"

    table = add_param(postgres_table_name)

    if settings.DEBUG or settings.TEST:
        databases = settings.DATABASES
        # Determine which database to use based on table name
        # Extract model name from postgres table name (e.g., "posthog_group" -> "group")
        model_name = postgres_table_name.replace("posthog_", "")
        db_name = "persons_db_writer" if model_name in PERSONS_DB_MODELS else "default"
        database = databases[db_name]

        address = add_param("db:5432")  # docker container for postgres from clickhouse
        db = add_param(database["NAME"])
        user = add_param(database["USER"])
        password = add_param(database["PASSWORD"])
    else:
        host_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST
        port_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT
        database_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE
        user_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_USER
        password_var = settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD

        if not host_var or not port_var or not database_var or not user_var or not password_var:
            raise ValueError("CLICKHOUSE_HOGQL_RDSPROXY env vars missing to create postgresql link from clickhouse")

        address = add_param(f"{host_var}:{port_var}")
        db = add_param(database_var)
        user = add_param(user_var)
        password = add_param(password_var)

    return f"postgresql({address}, {db}, {table}, {user}, {password})"


class PostgresTable(FunctionCallTable):
    requires_args: bool = False
    postgres_table_name: str
    access_scope: Optional[APIScopeObject] = None

    @property
    def primary_key(self) -> str:
        return _pk_column_for_pg_table(self.postgres_table_name)

    def to_printed_hogql(self):
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context):
        return build_function_call(self.postgres_table_name, context)
