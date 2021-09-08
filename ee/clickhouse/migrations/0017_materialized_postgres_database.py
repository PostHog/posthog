from infi.clickhouse_orm import migrations

operations = [
    migrations.RunSQL(
        """CREATE DATABASE postgres_posthog
											ENGINE = MaterializedPostgreSQL('db:5432', 'posthog', 'posthog', 'posthog')
											SETTINGS materialized_postgresql_max_block_size = 65536,
											materialized_postgresql_tables_list = 'posthog_person, posthog_persondistinctid';"""
    )
]
