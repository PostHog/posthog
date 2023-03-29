from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.data_beach import CREATE_DATA_BEACH_APPENDABLE_SQL

operations = [
    run_sql_with_exceptions(CREATE_DATA_BEACH_APPENDABLE_SQL),
]
