from infi.clickhouse_orm import migrations

from posthog.clickhouse import materialized_columns


def create_materialized_columns(database):
    materialize = materialized_columns.backend.materialize
    try:
        materialize("events", "$group_0", "$group_0")
        materialize("events", "$group_1", "$group_1")
        materialize("events", "$group_2", "$group_2")
        materialize("events", "$group_3", "$group_3")
        materialize("events", "$group_4", "$group_4")
    except ValueError:
        # Group is already materialized, skip
        pass


operations = [migrations.RunPython(create_materialized_columns)]
