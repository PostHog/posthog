from typing import Union, cast
from posthog.warehouse.models import ExternalDataSource
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
    Type4,
    Option,
)

FieldType = Union[
    SourceFieldInputConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
]


AVAILABLE_SOURCES: dict[ExternalDataSource.Type, SourceConfig] = {
    ExternalDataSource.Type.STRIPE: SourceConfig(
        name=ExternalDataSourceType.STRIPE,
        caption="""Enter your Stripe credentials to automatically pull your Stripe data into the PostHog Data warehouse.

You can find your account ID [in your Stripe dashboard](https://dashboard.stripe.com/settings/account), and create a secret key [here](https://dashboard.stripe.com/apikeys/create).

Currently, **read permissions are required** for the following resources:

- Under the **Core** resource type, select *read* for **Balance transaction sources**, **Charges**, **Customer**, **Product**, **Disputes**, and **Payouts**
- Under the **Billing** resource type, select *read* for **Invoice**, **Price**, **Subscription**, and **Credit notes**
- Under the **Connected** resource type, select *read* for the **entire resource**""",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="stripe_account_id",
                    label="Account id",
                    type=Type4.TEXT,
                    required=False,
                    placeholder="stripe_account_id",
                ),
                SourceFieldInputConfig(
                    name="stripe_secret_key",
                    label="API key",
                    type=Type4.PASSWORD,
                    required=True,
                    placeholder="rk_live_...",
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.HUBSPOT: SourceConfig(
        name=ExternalDataSourceType.HUBSPOT,
        caption="Select an existing Hubspot account to link to PostHog or create a new connection",
        fields=cast(
            list[FieldType],
            [
                SourceFieldOauthConfig(
                    name="hubspot_integration_id", label="Hubspot account", required=True, kind="hubspot"
                )
            ],
        ),
    ),
    ExternalDataSource.Type.POSTGRES: SourceConfig(
        name=ExternalDataSourceType.POSTGRES,
        caption="Enter your Postgres credentials to automatically pull your Postgres data into the PostHog Data warehouse",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="connection_string",
                    label="Connection string (optional)",
                    type=Type4.TEXT,
                    required=False,
                    placeholder="postgresql://user:password@localhost:5432/database",
                ),
                SourceFieldInputConfig(
                    name="host", label="Host", type=Type4.TEXT, required=True, placeholder="localhost"
                ),
                SourceFieldInputConfig(name="port", label="Port", type=Type4.NUMBER, required=True, placeholder="5432"),
                SourceFieldInputConfig(
                    name="database", label="Database", type=Type4.TEXT, required=True, placeholder="postgres"
                ),
                SourceFieldInputConfig(
                    name="user", label="User", type=Type4.TEXT, required=True, placeholder="postgres"
                ),
                SourceFieldInputConfig(
                    name="password", label="Password", type=Type4.PASSWORD, required=True, placeholder=""
                ),
                SourceFieldInputConfig(
                    name="schema", label="Schema", type=Type4.TEXT, required=True, placeholder="public"
                ),
                SourceFieldSwitchGroupConfig(
                    name="ssh-tunnel",
                    label="Use SSH tunnel?",
                    default=False,
                    fields=cast(
                        list[FieldType],
                        [
                            SourceFieldInputConfig(
                                name="host",
                                label="Tunnel host",
                                type=Type4.TEXT,
                                required=True,
                                placeholder="localhost",
                            ),
                            SourceFieldInputConfig(
                                name="port", label="Tunnel port", type=Type4.NUMBER, required=True, placeholder="22"
                            ),
                            SourceFieldSelectConfig(
                                name="auth_type",
                                label="Authentication type",
                                required=True,
                                defaultValue="password",
                                options=[
                                    Option(
                                        label="Password",
                                        value="password",
                                        fields=cast(
                                            list[FieldType],
                                            [
                                                SourceFieldInputConfig(
                                                    name="username",
                                                    label="Tunnel username",
                                                    type=Type4.TEXT,
                                                    required=True,
                                                    placeholder="User1",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="password",
                                                    label="Tunnel password",
                                                    type=Type4.PASSWORD,
                                                    required=True,
                                                    placeholder="",
                                                ),
                                            ],
                                        ),
                                    ),
                                    Option(
                                        label="Key pair",
                                        value="keypair",
                                        fields=cast(
                                            list[FieldType],
                                            [
                                                SourceFieldInputConfig(
                                                    name="username",
                                                    label="Tunnel username",
                                                    type=Type4.TEXT,
                                                    required=False,
                                                    placeholder="User1",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="private_key",
                                                    label="Tunnel private key",
                                                    type=Type4.TEXTAREA,
                                                    required=True,
                                                    placeholder="",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="passphrase",
                                                    label="Tunnel passphrase",
                                                    type=Type4.PASSWORD,
                                                    required=False,
                                                    placeholder="",
                                                ),
                                            ],
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.MYSQL: SourceConfig(
        name=ExternalDataSourceType.MY_SQL,
        caption="Enter your MySQL/MariaDB credentials to automatically pull your MySQL data into the PostHog Data warehouse.",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="host", label="Host", type=Type4.TEXT, required=True, placeholder="localhost"
                ),
                SourceFieldInputConfig(name="port", label="Port", type=Type4.NUMBER, required=True, placeholder="3306"),
                SourceFieldInputConfig(
                    name="database", label="Database", type=Type4.TEXT, required=True, placeholder="mysql"
                ),
                SourceFieldInputConfig(name="user", label="User", type=Type4.TEXT, required=True, placeholder="mysql"),
                SourceFieldInputConfig(
                    name="password", label="Password", type=Type4.PASSWORD, required=True, placeholder=""
                ),
                SourceFieldInputConfig(
                    name="schema", label="Schema", type=Type4.TEXT, required=True, placeholder="public"
                ),
                SourceFieldSelectConfig(
                    name="using_ssl",
                    label="Use SSL?",
                    required=True,
                    defaultValue="1",
                    options=[Option(label="Yes", value="1"), Option(label="No", value="0")],
                ),
                SourceFieldSwitchGroupConfig(
                    name="ssh-tunnel",
                    label="Use SSH tunnel?",
                    default=False,
                    fields=cast(
                        list[FieldType],
                        [
                            SourceFieldInputConfig(
                                name="host",
                                label="Tunnel host",
                                type=Type4.TEXT,
                                required=True,
                                placeholder="localhost",
                            ),
                            SourceFieldInputConfig(
                                name="port", label="Tunnel port", type=Type4.NUMBER, required=True, placeholder="22"
                            ),
                            SourceFieldSelectConfig(
                                name="auth_type",
                                label="Authentication type",
                                required=True,
                                defaultValue="password",
                                options=[
                                    Option(
                                        label="Password",
                                        value="password",
                                        fields=cast(
                                            list[FieldType],
                                            [
                                                SourceFieldInputConfig(
                                                    name="username",
                                                    label="Tunnel username",
                                                    type=Type4.TEXT,
                                                    required=True,
                                                    placeholder="User1",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="password",
                                                    label="Tunnel password",
                                                    type=Type4.PASSWORD,
                                                    required=True,
                                                    placeholder="",
                                                ),
                                            ],
                                        ),
                                    ),
                                    Option(
                                        label="Key pair",
                                        value="keypair",
                                        fields=cast(
                                            list[FieldType],
                                            [
                                                SourceFieldInputConfig(
                                                    name="username",
                                                    label="Tunnel username",
                                                    type=Type4.TEXT,
                                                    required=False,
                                                    placeholder="User1",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="private_key",
                                                    label="Tunnel private key",
                                                    type=Type4.TEXTAREA,
                                                    required=True,
                                                    placeholder="",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="passphrase",
                                                    label="Tunnel passphrase",
                                                    type=Type4.PASSWORD,
                                                    required=False,
                                                    placeholder="",
                                                ),
                                            ],
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.MSSQL: SourceConfig(
        name=ExternalDataSourceType.MSSQL,
        label="Microsoft SQL Server",
        caption="Enter your Microsoft SQL Server/Azure SQL Server credentials to automatically pull your SQL data into the PostHog Data warehouse.",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="host", label="Host", type=Type4.TEXT, required=True, placeholder="localhost"
                ),
                SourceFieldInputConfig(name="port", label="Port", type=Type4.NUMBER, required=True, placeholder="1433"),
                SourceFieldInputConfig(
                    name="database", label="Database", type=Type4.TEXT, required=True, placeholder="msdb"
                ),
                SourceFieldInputConfig(name="user", label="User", type=Type4.TEXT, required=True, placeholder="sa"),
                SourceFieldInputConfig(
                    name="password", label="Password", type=Type4.PASSWORD, required=True, placeholder=""
                ),
                SourceFieldInputConfig(
                    name="schema", label="Schema", type=Type4.TEXT, required=True, placeholder="dbo"
                ),
                SourceFieldSwitchGroupConfig(
                    name="ssh-tunnel",
                    label="Use SSH tunnel?",
                    default=False,
                    fields=cast(
                        list[FieldType],
                        [
                            SourceFieldInputConfig(
                                name="host",
                                label="Tunnel host",
                                type=Type4.TEXT,
                                required=True,
                                placeholder="localhost",
                            ),
                            SourceFieldInputConfig(
                                name="port", label="Tunnel port", type=Type4.NUMBER, required=True, placeholder="22"
                            ),
                            SourceFieldSelectConfig(
                                name="auth_type",
                                label="Authentication type",
                                required=True,
                                defaultValue="password",
                                options=[
                                    Option(
                                        label="Password",
                                        value="password",
                                        fields=cast(
                                            list[FieldType],
                                            [
                                                SourceFieldInputConfig(
                                                    name="username",
                                                    label="Tunnel username",
                                                    type=Type4.TEXT,
                                                    required=True,
                                                    placeholder="User1",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="password",
                                                    label="Tunnel password",
                                                    type=Type4.PASSWORD,
                                                    required=True,
                                                    placeholder="",
                                                ),
                                            ],
                                        ),
                                    ),
                                    Option(
                                        label="Key pair",
                                        value="keypair",
                                        fields=cast(
                                            list[FieldType],
                                            [
                                                SourceFieldInputConfig(
                                                    name="username",
                                                    label="Tunnel username",
                                                    type=Type4.TEXT,
                                                    required=False,
                                                    placeholder="User1",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="private_key",
                                                    label="Tunnel private key",
                                                    type=Type4.TEXTAREA,
                                                    required=True,
                                                    placeholder="",
                                                ),
                                                SourceFieldInputConfig(
                                                    name="passphrase",
                                                    label="Tunnel passphrase",
                                                    type=Type4.PASSWORD,
                                                    required=False,
                                                    placeholder="",
                                                ),
                                            ],
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.SNOWFLAKE: SourceConfig(
        name=ExternalDataSourceType.SNOWFLAKE,
        caption="Enter your Snowflake credentials to automatically pull your Snowflake data into the PostHog Data warehouse.",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="account_id", label="Account id", type=Type4.TEXT, required=True, placeholder=""
                ),
                SourceFieldInputConfig(
                    name="database",
                    label="Database",
                    type=Type4.TEXT,
                    required=True,
                    placeholder="snowflake_sample_data",
                ),
                SourceFieldInputConfig(
                    name="warehouse", label="Warehouse", type=Type4.TEXT, required=True, placeholder="COMPUTE_WAREHOUSE"
                ),
                SourceFieldSelectConfig(
                    name="auth_type",
                    label="Authentication type",
                    required=True,
                    defaultValue="password",
                    options=[
                        Option(
                            label="Password",
                            value="password",
                            fields=cast(
                                list[FieldType],
                                [
                                    SourceFieldInputConfig(
                                        name="username",
                                        label="Username",
                                        type=Type4.TEXT,
                                        required=True,
                                        placeholder="User1",
                                    ),
                                    SourceFieldInputConfig(
                                        name="password",
                                        label="Password",
                                        type=Type4.PASSWORD,
                                        required=True,
                                        placeholder="",
                                    ),
                                ],
                            ),
                        ),
                        Option(
                            label="Key pair",
                            value="keypair",
                            fields=cast(
                                list[FieldType],
                                [
                                    SourceFieldInputConfig(
                                        name="username",
                                        label="Username",
                                        type=Type4.TEXT,
                                        required=True,
                                        placeholder="User1",
                                    ),
                                    SourceFieldInputConfig(
                                        name="private_key",
                                        label="Private key",
                                        type=Type4.TEXTAREA,
                                        required=True,
                                        placeholder="",
                                    ),
                                    SourceFieldInputConfig(
                                        name="passphrase",
                                        label="Passphrase",
                                        type=Type4.PASSWORD,
                                        required=False,
                                        placeholder="",
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
                SourceFieldInputConfig(
                    name="role", label="Role (optional)", type=Type4.TEXT, required=False, placeholder="ACCOUNTADMIN"
                ),
                SourceFieldInputConfig(
                    name="schema", label="Schema", type=Type4.TEXT, required=True, placeholder="public"
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.ZENDESK: SourceConfig(
        name=ExternalDataSourceType.ZENDESK,
        caption="Enter your Zendesk API key to automatically pull your Zendesk support data into the PostHog Data warehouse.",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="subdomain", label="Zendesk subdomain", type=Type4.TEXT, required=True, placeholder=""
                ),
                SourceFieldInputConfig(name="api_key", label="API key", type=Type4.TEXT, required=True, placeholder=""),
                SourceFieldInputConfig(
                    name="email_address", label="Zendesk email address", type=Type4.EMAIL, required=True, placeholder=""
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.SALESFORCE: SourceConfig(
        name=ExternalDataSourceType.SALESFORCE,
        caption="Select an existing Salesforce account to link to PostHog or create a new connection",
        fields=cast(
            list[FieldType],
            [
                SourceFieldOauthConfig(
                    name="salesforce_integration_id", label="Salesforce account", required=True, kind="salesforce"
                )
            ],
        ),
    ),
    ExternalDataSource.Type.VITALLY: SourceConfig(
        name=ExternalDataSourceType.VITALLY,
        caption="",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="secret_token", label="Secret token", type=Type4.TEXT, required=True, placeholder="sk_live_..."
                ),
                SourceFieldSelectConfig(
                    name="region",
                    label="Vitally region",
                    required=True,
                    defaultValue="EU",
                    options=[
                        Option(label="EU", value="EU"),
                        Option(
                            label="US",
                            value="US",
                            fields=cast(
                                list[FieldType],
                                [
                                    SourceFieldInputConfig(
                                        name="subdomain",
                                        label="Vitally subdomain",
                                        type=Type4.TEXT,
                                        required=True,
                                        placeholder="",
                                    )
                                ],
                            ),
                        ),
                    ],
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.BIGQUERY: SourceConfig(
        name=ExternalDataSourceType.BIG_QUERY,
        caption="",
        fields=cast(
            list[FieldType],
            [
                SourceFieldFileUploadConfig(
                    name="key_file", label="Google Cloud JSON key file", fileFormat=".json", required=True
                ),
                SourceFieldInputConfig(
                    name="dataset_id", label="Dataset ID", type=Type4.TEXT, required=True, placeholder=""
                ),
                SourceFieldSwitchGroupConfig(
                    name="temporary-dataset",
                    label="Use a different dataset for the temporary tables?",
                    caption="We have to create and delete temporary tables when querying your data, this is a requirement of querying large BigQuery tables. We can use a different dataset if you'd like to limit the permissions available to the service account provided.",
                    default=False,
                    fields=cast(
                        list[FieldType],
                        [
                            SourceFieldInputConfig(
                                name="temporary_dataset_id",
                                label="Dataset ID for temporary tables",
                                type=Type4.TEXT,
                                required=True,
                                placeholder="",
                            )
                        ],
                    ),
                ),
                SourceFieldSwitchGroupConfig(
                    name="dataset_project",
                    label="Use a different project for the dataset than your service account project?",
                    caption="If the dataset you're wanting to sync exists in a different project than that of your service account, use this to provide the project ID of the BigQuery dataset.",
                    default=False,
                    fields=cast(
                        list[FieldType],
                        [
                            SourceFieldInputConfig(
                                name="dataset_project_id",
                                label="Project ID for dataset",
                                type=Type4.TEXT,
                                required=True,
                                placeholder="",
                            )
                        ],
                    ),
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.CHARGEBEE: SourceConfig(
        name=ExternalDataSourceType.CHARGEBEE,
        caption="",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(name="api_key", label="API key", type=Type4.TEXT, required=True, placeholder=""),
                SourceFieldInputConfig(
                    name="site_name", label="Site name (subdomain)", type=Type4.TEXT, required=True, placeholder=""
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.TEMPORALIO: SourceConfig(
        name=ExternalDataSourceType.TEMPORAL_IO,
        label="Temporal.io",
        caption="",
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(name="host", label="Host", type=Type4.TEXT, required=True, placeholder=""),
                SourceFieldInputConfig(name="port", label="Port", type=Type4.TEXT, required=True, placeholder=""),
                SourceFieldInputConfig(
                    name="namespace", label="Namespace", type=Type4.TEXT, required=True, placeholder=""
                ),
                SourceFieldInputConfig(
                    name="encryption_key", label="Encryption key", type=Type4.TEXT, required=False, placeholder=""
                ),
                SourceFieldInputConfig(
                    name="server_client_root_ca",
                    label="Server client root CA",
                    type=Type4.TEXTAREA,
                    required=True,
                    placeholder="",
                ),
                SourceFieldInputConfig(
                    name="client_certificate",
                    label="Client certificate",
                    type=Type4.TEXTAREA,
                    required=True,
                    placeholder="",
                ),
                SourceFieldInputConfig(
                    name="client_private_key",
                    label="Client private key",
                    type=Type4.TEXTAREA,
                    required=True,
                    placeholder="",
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.GOOGLEADS: SourceConfig(
        name=ExternalDataSourceType.GOOGLE_ADS,
        label="Google Ads",
        caption="Ensure you have granted PostHog access to your Google Ads account, learn how to do this in [the docs](https://posthog.com/docs/cdp/sources/google-ads).",
        betaSource=True,
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="customer_id", label="Customer ID", type=Type4.TEXT, required=True, placeholder=""
                ),
                SourceFieldOauthConfig(
                    name="google_ads_integration_id", label="Google Ads account", required=True, kind="google-ads"
                ),
            ],
        ),
    ),
    ExternalDataSource.Type.DOIT: SourceConfig(
        name=ExternalDataSourceType.DO_IT,
        label="DoIt",
        caption="",
        fields=cast(
            list[FieldType],
            [SourceFieldInputConfig(name="api_key", label="API key", type=Type4.TEXT, required=True, placeholder="")],
        ),
    ),
    ExternalDataSource.Type.GOOGLESHEETS: SourceConfig(
        name=ExternalDataSourceType.GOOGLE_SHEETS,
        label="Google Sheets",
        caption="Ensure you have granted PostHog access to your Google Sheet as instructed in the [documentation](https://posthog.com/docs/cdp/sources/google-sheets)",
        betaSource=True,
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="spreadsheet_url", label="Spreadsheet URL", type=Type4.TEXT, required=True, placeholder=""
                )
            ],
        ),
    ),
    ExternalDataSource.Type.MONGODB: SourceConfig(
        name=ExternalDataSourceType.MONGO_DB,
        label="MongoDB",
        caption="Enter your MongoDB connection string to automatically pull your MongoDB data into the PostHog Data warehouse.",
        betaSource=True,
        fields=cast(
            list[FieldType],
            [
                SourceFieldInputConfig(
                    name="connection_string",
                    label="Connection String",
                    type=Type4.TEXT,
                    required=True,
                    placeholder="mongodb://username:password@host:port/database?authSource=admin",
                )
            ],
        ),
    ),
    ExternalDataSource.Type.METAADS: SourceConfig(
        name=ExternalDataSourceType.META_ADS,
        label="Meta Ads",
        caption="",
        fields=cast(list[FieldType], []),
        unreleasedSource=True,
    ),
    ExternalDataSource.Type.KLAVIYO: SourceConfig(
        name=ExternalDataSourceType.KLAVIYO,
        label="Klaviyo",
        caption="",
        fields=cast(list[FieldType], []),
        unreleasedSource=True,
    ),
    ExternalDataSource.Type.MAILCHIMP: SourceConfig(
        name=ExternalDataSourceType.MAILCHIMP,
        label="Mailchimp",
        caption="",
        fields=cast(list[FieldType], []),
        unreleasedSource=True,
    ),
    ExternalDataSource.Type.BRAZE: SourceConfig(
        name=ExternalDataSourceType.BRAZE,
        label="Braze",
        caption="",
        fields=cast(list[FieldType], []),
        unreleasedSource=True,
    ),
    ExternalDataSource.Type.MAILJET: SourceConfig(
        name=ExternalDataSourceType.MAILJET,
        label="Mailjet",
        caption="",
        fields=cast(list[FieldType], []),
        unreleasedSource=True,
    ),
    ExternalDataSource.Type.REDSHIFT: SourceConfig(
        name=ExternalDataSourceType.REDSHIFT,
        label="Redshift",
        caption="",
        fields=cast(list[FieldType], []),
        unreleasedSource=True,
    ),
}
