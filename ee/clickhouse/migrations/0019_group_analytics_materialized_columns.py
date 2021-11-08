from ee.clickhouse.materialized_columns.columns import materialize

materialize("events", "$group_0", "$group_0")
materialize("events", "$group_1", "$group_1")
materialize("events", "$group_2", "$group_2")
materialize("events", "$group_3", "$group_3")
materialize("events", "$group_4", "$group_4")

operations = []  # type: ignore
