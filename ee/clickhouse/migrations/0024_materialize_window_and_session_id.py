from infi.clickhouse_orm import migrations

from ee.clickhouse.materialized_columns.columns import materialize


def create_materialized_columns(database):
    try:
        materialize("events", "$session_id", "mat_session_id")
    except ValueError:
        # session_id is already materialized, skip
        pass
    try:
        materialize("events", "$window_id", "mat_window_id")
    except ValueError:
        # window_id is already materialized, skip
        pass


operations = [migrations.RunPython(create_materialized_columns)]
