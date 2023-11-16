from infi.clickhouse_orm import migrations

from posthog.clickhouse.materialized_columns import materialize

# 0026_fix_materialized_window_and_session_ids.py does something more complex, do we need to check the 'mat_' prefix as well?


def create_materialized_columns(database):
    try:
        materialize("events", "$lib_version", "$lib_version")
    except ValueError:
        # $lib_version is already materialized, skip
        pass


operations = [migrations.RunPython(create_materialized_columns)]
