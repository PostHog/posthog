from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from posthog.temporal.data_imports.sources.generated_configs import (
    BigQuerySourceConfig,
    MSSQLSourceConfig,
    MySQLSourceConfig,
    PostgresSourceConfig,
    SnowflakeSourceConfig,
    VitallySourceConfig,
    ZendeskSourceConfig,
)

from products.data_warehouse.backend.models import ExternalDataSource as ExternalDataSourceModel
from products.data_warehouse.backend.types import ExternalDataSourceType


class DWHSourceRefactorMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0806_scheduledchange_failure_count_and_more"
    migrate_to = "0807_dwh_source_refactor"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        ExternalDataSource: ExternalDataSourceModel = apps.get_model("posthog", "ExternalDataSource")

        self.organization = Organization.objects.create(name="o1")
        self.project = Project.objects.create(organization=self.organization, name="p1", id=1000001)
        self.team = Team.objects.create(organization=self.organization, name="t1", project=self.project)

        self.bigquery_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.BIGQUERY,
            job_inputs={
                "token_uri": "token_uri",
                "dataset_id": "dataset_id",
                "project_id": "project_id",
                "private_key": "private_key",
                "client_email": "client_email",
                "private_key_id": "private_key_id",
                "dataset_project_id": "dataset_project_id",
                "temporary_dataset_id": "temporary_dataset_id",
                "using_temporary_dataset": "True",
                "using_custom_dataset_project": "True",
            },
        )
        self.mssql_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.MSSQL,
            job_inputs={
                "host": "host",
                "port": "1433",
                "user": "user",
                "schema": "schema",
                "database": "database",
                "password": "password",
                "using_ssl": "True",
                "ssh_tunnel_host": "host",
                "ssh_tunnel_port": "22",
                "ssh_tunnel_enabled": "True",
                "ssh_tunnel_auth_type": "password",
                "ssh_tunnel_auth_type_password": "password",
                "ssh_tunnel_auth_type_username": "username",
                "ssh_tunnel_auth_type_passphrase": "",
                "ssh_tunnel_auth_type_private_key": "",
            },
        )
        self.mysql_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.MYSQL,
            job_inputs={
                "host": "host",
                "port": "1433",
                "user": "user",
                "schema": "schema",
                "database": "database",
                "password": "password",
                "using_ssl": "True",
                "ssh_tunnel_host": "host",
                "ssh_tunnel_port": "22",
                "ssh_tunnel_enabled": "True",
                "ssh_tunnel_auth_type": "password",
                "ssh_tunnel_auth_type_password": "password",
                "ssh_tunnel_auth_type_username": "username",
                "ssh_tunnel_auth_type_passphrase": "",
                "ssh_tunnel_auth_type_private_key": "",
            },
        )
        self.postgres_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "host": "host",
                "port": "1433",
                "user": "user",
                "schema": "schema",
                "database": "database",
                "password": "password",
                "using_ssl": "True",
                "ssh_tunnel_host": "host",
                "ssh_tunnel_port": "22",
                "ssh_tunnel_enabled": "True",
                "ssh_tunnel_auth_type": "keypair",
                "ssh_tunnel_auth_type_password": "",
                "ssh_tunnel_auth_type_username": "username",
                "ssh_tunnel_auth_type_passphrase": "passphrase",
                "ssh_tunnel_auth_type_private_key": "private_key",
            },
        )
        self.snowflake_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.SNOWFLAKE,
            job_inputs={
                "role": "role",
                "user": "user",
                "schema": "schema",
                "database": "database",
                "password": "password",
                "auth_type": "password",
                "warehouse": "warehouse",
                "account_id": "account_id",
                "passphrase": "",
                "private_key": "",
            },
        )
        self.vitally_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.VITALLY,
            job_inputs={
                "region": "US",
                "subdomain": "subdomain",
                "secret_token": "secret_token",
            },
        )
        self.zendesk_source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.ZENDESK,
            job_inputs={
                "zendesk_api_key": "api_key",
                "zendesk_subdomain": "subdomain",
                "zendesk_login_method": "api_key",
                "zendesk_email_address": "email_address",
            },
        )

    def test_migration(self):
        bigquery_source_pre_migrated_job_inputs = self.bigquery_source.job_inputs
        mssql_source_pre_migrated_job_inputs = self.mssql_source.job_inputs
        mysql_source_pre_migrated_job_inputs = self.mysql_source.job_inputs
        postgres_source_pre_migrated_job_inputs = self.postgres_source.job_inputs
        snowflake_source_pre_migrated_job_inputs = self.snowflake_source.job_inputs
        vitally_source_pre_migrated_job_inputs = self.vitally_source.job_inputs
        zendesk_source_pre_migrated_job_inputs = self.zendesk_source.job_inputs

        self.bigquery_source.refresh_from_db()
        self.mssql_source.refresh_from_db()
        self.mysql_source.refresh_from_db()
        self.postgres_source.refresh_from_db()
        self.snowflake_source.refresh_from_db()
        self.vitally_source.refresh_from_db()
        self.zendesk_source.refresh_from_db()

        assert self.bigquery_source.job_inputs is not None
        assert self.mssql_source.job_inputs is not None
        assert self.mysql_source.job_inputs is not None
        assert self.postgres_source.job_inputs is not None
        assert self.snowflake_source.job_inputs is not None
        assert self.vitally_source.job_inputs is not None
        assert self.zendesk_source.job_inputs is not None

        bigquery_config = BigQuerySourceConfig.from_dict(self.bigquery_source.job_inputs)
        mssql_config = MSSQLSourceConfig.from_dict(self.mssql_source.job_inputs)
        mysql_config = MySQLSourceConfig.from_dict(self.mysql_source.job_inputs)
        postgres_config = PostgresSourceConfig.from_dict(self.postgres_source.job_inputs)
        snowflake_config = SnowflakeSourceConfig.from_dict(self.snowflake_source.job_inputs)
        vitally_config = VitallySourceConfig.from_dict(self.vitally_source.job_inputs)
        zendesk_config = ZendeskSourceConfig.from_dict(self.zendesk_source.job_inputs)

        # Pre-migration job inputs
        assert bigquery_source_pre_migrated_job_inputs == self.bigquery_source.job_inputs["pre_migration_job_inputs"]
        assert mssql_source_pre_migrated_job_inputs == self.mssql_source.job_inputs["pre_migration_job_inputs"]
        assert mysql_source_pre_migrated_job_inputs == self.mysql_source.job_inputs["pre_migration_job_inputs"]
        assert postgres_source_pre_migrated_job_inputs == self.postgres_source.job_inputs["pre_migration_job_inputs"]
        assert snowflake_source_pre_migrated_job_inputs == self.snowflake_source.job_inputs["pre_migration_job_inputs"]
        assert vitally_source_pre_migrated_job_inputs == self.vitally_source.job_inputs["pre_migration_job_inputs"]
        assert zendesk_source_pre_migrated_job_inputs == self.zendesk_source.job_inputs["pre_migration_job_inputs"]

        # BigQuery
        assert bigquery_config.key_file.project_id == "project_id"
        assert bigquery_config.key_file.private_key_id == "private_key_id"
        assert bigquery_config.key_file.private_key == "private_key"
        assert bigquery_config.key_file.client_email == "client_email"
        assert bigquery_config.key_file.token_uri == "token_uri"
        assert bigquery_config.dataset_id == "dataset_id"
        assert bigquery_config.temporary_dataset is not None
        assert bigquery_config.temporary_dataset.enabled is True
        assert bigquery_config.temporary_dataset.temporary_dataset_id == "temporary_dataset_id"
        assert bigquery_config.dataset_project is not None
        assert bigquery_config.dataset_project.enabled is True
        assert bigquery_config.dataset_project.dataset_project_id == "dataset_project_id"

        # MSSQL
        assert mssql_config.host == "host"
        assert mssql_config.port == 1433
        assert mssql_config.database == "database"
        assert mssql_config.user == "user"
        assert mssql_config.password == "password"
        assert mssql_config.schema == "schema"
        assert mssql_config.ssh_tunnel is not None
        assert mssql_config.ssh_tunnel.enabled is True
        assert mssql_config.ssh_tunnel.host == "host"
        assert mssql_config.ssh_tunnel.port == 22
        assert mssql_config.ssh_tunnel.auth is not None
        assert mssql_config.ssh_tunnel.auth.type == "password"
        assert mssql_config.ssh_tunnel.auth.username == "username"
        assert mssql_config.ssh_tunnel.auth.password == "password"
        assert mssql_config.ssh_tunnel.auth.private_key == ""
        assert mssql_config.ssh_tunnel.auth.passphrase == ""

        # MySQL
        assert mysql_config.host == "host"
        assert mysql_config.port == 1433
        assert mysql_config.database == "database"
        assert mysql_config.user == "user"
        assert mysql_config.password == "password"
        assert mysql_config.schema == "schema"
        assert mysql_config.using_ssl is True
        assert mysql_config.ssh_tunnel is not None
        assert mysql_config.ssh_tunnel.enabled is True
        assert mysql_config.ssh_tunnel.host == "host"
        assert mysql_config.ssh_tunnel.port == 22
        assert mysql_config.ssh_tunnel.auth is not None
        assert mysql_config.ssh_tunnel.auth.type == "password"
        assert mysql_config.ssh_tunnel.auth.username == "username"
        assert mysql_config.ssh_tunnel.auth.password == "password"
        assert mysql_config.ssh_tunnel.auth.private_key == ""
        assert mysql_config.ssh_tunnel.auth.passphrase == ""

        # Postgres
        assert postgres_config.host == "host"
        assert postgres_config.port == 1433
        assert postgres_config.database == "database"
        assert postgres_config.user == "user"
        assert postgres_config.password == "password"
        assert postgres_config.schema == "schema"
        assert postgres_config.ssh_tunnel is not None
        assert postgres_config.ssh_tunnel.enabled is True
        assert postgres_config.ssh_tunnel.host == "host"
        assert postgres_config.ssh_tunnel.port == 22
        assert postgres_config.ssh_tunnel.auth is not None
        assert postgres_config.ssh_tunnel.auth.type == "keypair"
        assert postgres_config.ssh_tunnel.auth.username == "username"
        assert postgres_config.ssh_tunnel.auth.password == ""
        assert postgres_config.ssh_tunnel.auth.private_key == "private_key"
        assert postgres_config.ssh_tunnel.auth.passphrase == "passphrase"

        # Snowflake snowflake_config
        assert snowflake_config.account_id == "account_id"
        assert snowflake_config.database == "database"
        assert snowflake_config.warehouse == "warehouse"
        assert snowflake_config.role == "role"
        assert snowflake_config.schema == "schema"
        assert snowflake_config.auth_type is not None
        assert snowflake_config.auth_type.selection == "password"
        assert snowflake_config.auth_type.user == "user"
        assert snowflake_config.auth_type.password == "password"
        assert snowflake_config.auth_type.private_key == ""
        assert snowflake_config.auth_type.passphrase == ""

        # Vitally
        assert vitally_config.secret_token == "secret_token"
        assert vitally_config.region is not None
        assert vitally_config.region.selection == "US"
        assert vitally_config.region.subdomain == "subdomain"

        # Zendesk
        assert zendesk_config.subdomain == "subdomain"
        assert zendesk_config.api_key == "api_key"
        assert zendesk_config.email_address == "email_address"
