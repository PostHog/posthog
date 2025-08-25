from posthog.temporal.data_imports.sources.generated_configs import (
    BigQuerySourceConfig,
    ChargebeeSourceConfig,
    DoItSourceConfig,
    GoogleAdsSourceConfig,
    GoogleSheetsSourceConfig,
    HubspotSourceConfig,
    MetaAdsSourceConfig,
    MongoDBSourceConfig,
    MSSQLSourceConfig,
    MySQLSourceConfig,
    PostgresSourceConfig,
    SalesforceSourceConfig,
    SnowflakeSourceConfig,
    StripeSourceConfig,
    TemporalIOSourceConfig,
    VitallySourceConfig,
    ZendeskSourceConfig,
)


def test_bigquery_config():
    config = BigQuerySourceConfig.from_dict(
        {
            "key_file": {
                "project_id": "project_id",
                "private_key_id": "private_key_id",
                "private_key": "private_key",
                "client_email": "client_email",
                "token_uri": "token_uri",
            },
            "dataset_id": "dataset_id",
            "temporary-dataset": {"enabled": False, "temporary_dataset_id": ""},
            "dataset_project": {"enabled": False, "dataset_project_id": ""},
        }
    )

    assert config.key_file.project_id == "project_id"
    assert config.key_file.private_key_id == "private_key_id"
    assert config.key_file.private_key == "private_key"
    assert config.key_file.client_email == "client_email"
    assert config.key_file.token_uri == "token_uri"
    assert config.dataset_id == "dataset_id"
    assert config.temporary_dataset is not None
    assert config.temporary_dataset.enabled is False
    assert config.temporary_dataset.temporary_dataset_id == ""
    assert config.dataset_project is not None
    assert config.dataset_project.enabled is False
    assert config.dataset_project.dataset_project_id == ""


def test_chargebee_config():
    config = ChargebeeSourceConfig.from_dict({"api_key": "api_key", "site_name": "subdomain"})
    assert config.api_key == "api_key"
    assert config.site_name == "subdomain"


def test_doit_config():
    config = DoItSourceConfig.from_dict({"api_key": "api_key"})
    assert config.api_key == "api_key"


def test_google_ads_config():
    config = GoogleAdsSourceConfig.from_dict({"customer_id": "123", "google_ads_integration_id": 1})
    assert config.customer_id == "123"
    assert config.google_ads_integration_id == 1


def test_google_sheets_config():
    config = GoogleSheetsSourceConfig.from_dict({"spreadsheet_url": "google.com"})
    assert config.spreadsheet_url == "google.com"


def test_hubspot_config():
    config = HubspotSourceConfig.from_dict({"hubspot_integration_id": 1})
    assert config.hubspot_integration_id == 1


def test_mssql_config():
    config = MSSQLSourceConfig.from_dict(
        {
            "host": "host",
            "port": 1433,
            "database": "database",
            "user": "user",
            "password": "password",
            "schema": "schema",
            "ssh_tunnel": {
                "enabled": True,
                "host": "host",
                "port": 22,
                "auth_type": {
                    "selection": "password",
                    "username": "username",
                    "password": "password",
                    "private_key": "",
                    "passphrase": "",
                },
            },
        }
    )

    assert config.host == "host"
    assert config.port == 1433
    assert config.database == "database"
    assert config.user == "user"
    assert config.password == "password"
    assert config.schema == "schema"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is True
    assert config.ssh_tunnel.host == "host"
    assert config.ssh_tunnel.port == 22
    assert config.ssh_tunnel.auth is not None
    assert config.ssh_tunnel.auth.type == "password"
    assert config.ssh_tunnel.auth.username == "username"
    assert config.ssh_tunnel.auth.password == "password"
    assert config.ssh_tunnel.auth.private_key == ""
    assert config.ssh_tunnel.auth.passphrase == ""


def test_meta_ads_config():
    config = MetaAdsSourceConfig.from_dict({"account_id": "123", "meta_ads_integration_id": 1})
    assert config.account_id == "123"
    assert config.meta_ads_integration_id == 1


def test_mongo_config():
    config = MongoDBSourceConfig.from_dict({"connection_string": "connection_string"})
    assert config.connection_string == "connection_string"


def test_mysql_config():
    config = MySQLSourceConfig.from_dict(
        {
            "host": "host",
            "port": 1433,
            "database": "database",
            "user": "user",
            "password": "password",
            "schema": "schema",
            "using_ssl": "true",
            "ssh_tunnel": {
                "enabled": True,
                "host": "host",
                "port": 22,
                "auth_type": {
                    "selection": "password",
                    "username": "username",
                    "password": "password",
                    "private_key": "",
                    "passphrase": "",
                },
            },
        }
    )

    assert config.host == "host"
    assert config.port == 1433
    assert config.database == "database"
    assert config.user == "user"
    assert config.password == "password"
    assert config.schema == "schema"
    assert config.using_ssl is True
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is True
    assert config.ssh_tunnel.host == "host"
    assert config.ssh_tunnel.port == 22
    assert config.ssh_tunnel.auth is not None
    assert config.ssh_tunnel.auth.type == "password"
    assert config.ssh_tunnel.auth.username == "username"
    assert config.ssh_tunnel.auth.password == "password"
    assert config.ssh_tunnel.auth.private_key == ""
    assert config.ssh_tunnel.auth.passphrase == ""


def test_postgres_config():
    config = PostgresSourceConfig.from_dict(
        {
            "host": "host",
            "port": 1433,
            "database": "database",
            "user": "user",
            "password": "password",
            "schema": "schema",
            "ssh_tunnel": {
                "enabled": True,
                "host": "host",
                "port": 22,
                "auth_type": {
                    "selection": "password",
                    "username": "username",
                    "password": "password",
                    "private_key": "",
                    "passphrase": "",
                },
            },
        }
    )

    assert config.host == "host"
    assert config.port == 1433
    assert config.database == "database"
    assert config.user == "user"
    assert config.password == "password"
    assert config.schema == "schema"
    assert config.ssh_tunnel is not None
    assert config.ssh_tunnel.enabled is True
    assert config.ssh_tunnel.host == "host"
    assert config.ssh_tunnel.port == 22
    assert config.ssh_tunnel.auth is not None
    assert config.ssh_tunnel.auth.type == "password"
    assert config.ssh_tunnel.auth.username == "username"
    assert config.ssh_tunnel.auth.password == "password"
    assert config.ssh_tunnel.auth.private_key == ""
    assert config.ssh_tunnel.auth.passphrase == ""


def test_salesforce_config():
    config = SalesforceSourceConfig.from_dict({"salesforce_integration_id": 1})
    assert config.salesforce_integration_id == 1


def test_snowflake_config():
    config = SnowflakeSourceConfig.from_dict(
        {
            "account_id": "account_id",
            "database": "database",
            "warehouse": "warehouse",
            "auth_type": {
                "selection": "password",
                "user": "user",
                "password": "password",
                "private_key": "",
                "passphrase": "",
            },
            "role": "role",
            "schema": "schema",
        }
    )
    assert config.account_id == "account_id"
    assert config.database == "database"
    assert config.warehouse == "warehouse"
    assert config.role == "role"
    assert config.schema == "schema"
    assert config.auth_type is not None
    assert config.auth_type.selection == "password"
    assert config.auth_type.user == "user"
    assert config.auth_type.password == "password"
    assert config.auth_type.private_key == ""
    assert config.auth_type.passphrase == ""


def test_stripe_config():
    config = StripeSourceConfig.from_dict({"stripe_account_id": "acct_id", "stripe_secret_key": "api_key"})
    assert config.stripe_account_id == "acct_id"
    assert config.stripe_secret_key == "api_key"


def test_temporal_config():
    config = TemporalIOSourceConfig.from_dict(
        {
            "host": "host",
            "port": "22",
            "namespace": "namespace",
            "encryption_key": "encryption_key",
            "server_client_root_ca": "server_client_root_ca",
            "client_certificate": "client_certificate",
            "client_private_key": "client_private_key",
        }
    )
    assert config.host == "host"
    assert config.port == "22"
    assert config.namespace == "namespace"
    assert config.encryption_key == "encryption_key"
    assert config.server_client_root_ca == "server_client_root_ca"
    assert config.client_certificate == "client_certificate"
    assert config.client_private_key == "client_private_key"


def test_vitally_config():
    config = VitallySourceConfig.from_dict(
        {"secret_token": "secret_token", "region": {"selection": "US", "subdomain": "subdomain"}}
    )
    assert config.secret_token == "secret_token"
    assert config.region is not None
    assert config.region.selection == "US"
    assert config.region.subdomain == "subdomain"


def test_zendesk_config():
    config = ZendeskSourceConfig.from_dict(
        {"subdomain": "subdomain", "api_key": "api_key", "email_address": "email_address"}
    )
    assert config.subdomain == "subdomain"
    assert config.api_key == "api_key"
    assert config.email_address == "email_address"
