import os

from posthog.settings.utils import get_from_env, get_list, str_to_bool

AIRBYTE_API_KEY = os.getenv("AIRBYTE_API_KEY", None)
AIRBYTE_BUCKET_REGION = os.getenv("AIRBYTE_BUCKET_REGION", None)
AIRBYTE_BUCKET_KEY = os.getenv("AIRBYTE_BUCKET_KEY", None)
AIRBYTE_BUCKET_SECRET = os.getenv("AIRBYTE_BUCKET_SECRET", None)
AIRBYTE_BUCKET_DOMAIN = os.getenv("AIRBYTE_BUCKET_DOMAIN", None)
# for DLT
BUCKET_URL = os.getenv("BUCKET_URL", None)
AIRBYTE_BUCKET_NAME = os.getenv("AIRBYTE_BUCKET_NAME", None)
BUCKET = "test-pipeline"

PYARROW_DEBUG_LOGGING = get_from_env("PYARROW_DEBUG_LOGGING", False, type_cast=str_to_bool)

# Temporary, using it to maintain existing teams in old  bigquery source.
# After further testing this will be removed and all teams moved to new source.
OLD_BIGQUERY_SOURCE_TEAM_IDS: list[str] = get_list(os.getenv("OLD_BIGQUERY_SOURCE_TEAM_IDS", ""))

# Temporary, using it to maintain existing teams in old MS SQL Server source.
# After further testing this will be removed and all teams moved to new source.
OLD_MSSQL_SOURCE_TEAM_IDS: list[str] = get_list(os.getenv("OLD_MSSQL_SOURCE_TEAM_IDS", ""))

GOOGLE_ADS_DEVELOPER_TOKEN: str | None = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL")
GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY")
GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI: str | None = os.getenv("GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI")
