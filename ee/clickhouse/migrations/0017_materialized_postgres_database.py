from infi.clickhouse_orm import migrations

operations = [
    migrations.RunSQL(
        """CREATE DATABASE postgres_posthog
											ENGINE = MaterializedPostgreSQL('db:5432', 'posthog', 'posthog', 'posthog')
											SETTINGS materialized_postgresql_max_block_size = 65536,
											materialized_postgresql_tables_list = 'posthog_person, posthog_persondistinctid';"""
    ),
    migrations.RunSQL(
        """CREATE TABLE posthog.pg_person (
					id UInt64,
					created_at DateTime64,
					team_id UInt64,
					properties String,
					is_identified bool,
					is_deleted bool)
				ENGINE = MaterializedPostgreSQL('db:5432', 'posthog', 'posthog_person', 'posthog', 'posthog')
				PRIMARY KEY id;"""
    ),
]
