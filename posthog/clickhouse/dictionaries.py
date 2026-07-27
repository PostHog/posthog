from django.conf import settings

from posthog.clickhouse.client.connection import ClickHouseUser, get_clickhouse_creds


def dictionary_source_clickhouse(table: str) -> str:
    """Build a dictionary SOURCE(CLICKHOUSE(...)) clause authed as the dedicated
    low-privilege dict_reader user (falls back to the default user when the
    CLICKHOUSE_DICT_READER_* env vars are unset)."""
    user, password = get_clickhouse_creds(ClickHouseUser.DICT_READER)
    connection_settings = f"TABLE {table} DB '{settings.CLICKHOUSE_DATABASE}'"
    if user:
        connection_settings += f" USER '{user}'"
    if password:
        connection_settings += f" PASSWORD '{password}'"
    return f"SOURCE(CLICKHOUSE({connection_settings}))"
