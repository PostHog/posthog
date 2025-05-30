import json
import os

import pyarrow as pa
import pytest
from django.test import override_settings

from posthog.temporal.data_imports.pipelines.google_ads import GoogleAdsServiceAccountSourceConfig, get_schemas

SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS" not in os.environ
    and "GOOGLE_DEVELOPER_TOKEN" not in os.environ
    and "GOOGLE_ADS_CUSTOMER_ID" not in os.environ,
    reason="Google service account credentials and/or developer token not set in environment",
)


@pytest.fixture
def customer_id() -> str:
    """Return customer id if available in environment, otherwise a default."""
    customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", None)

    if not customer_id:
        return "1111111111"
    else:
        return customer_id


@pytest.fixture
def developer_token() -> str:
    """Return developer token if available in environment, otherwise a default."""
    developer_token = os.getenv("GOOGLE_DEVELOPER_TOKEN", None)

    if not developer_token:
        return "aaabbbccc111222333"
    else:
        return developer_token


@pytest.fixture
def service_account_config() -> dict[str, str]:
    """Return a Service Account configuration dictionary to use in tests."""
    credentials_file_path = os.environ["GOOGLE_SERVICE_ACCOUNT_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    return {
        "private_key": credentials["private_key"],
        "private_key_id": credentials["private_key_id"],
        "token_uri": credentials["token_uri"],
        "client_email": credentials["client_email"],
    }


def test_google_ads_source_config_loads(customer_id: str, developer_token: str):
    """Test basic case of source configuration loading."""
    private_key = "private_key"
    private_key_id = "id"
    client_email = "posthog@posthog.com"
    token_uri = "https://posthog.com"
    developer_token = developer_token

    job_inputs = {
        "resource_name": "campaign",
        "customer_id": customer_id,
    }

    with override_settings(
        GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY=private_key,
        GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID=private_key_id,
        GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL=client_email,
        GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI=token_uri,
        GOOGLE_ADS_DEVELOPER_TOKEN=developer_token,
    ):
        cfg = GoogleAdsServiceAccountSourceConfig.from_dict(job_inputs)

    assert cfg.private_key == private_key
    assert cfg.private_key_id == private_key_id
    assert cfg.client_email == client_email
    assert cfg.token_uri == token_uri
    assert cfg.developer_token == developer_token
    assert cfg.customer_id == customer_id
    assert cfg.resource_name == "campaign"


@SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS
def test_get_schemas(customer_id: str, developer_token: str, service_account_config: dict[str, str]):
    """Test get_schemas returns well-known schemas.

    This test is not exhaustive and merely limits itself to asserting a handful
    of well-known schemas are returned.
    """
    cfg = GoogleAdsServiceAccountSourceConfig(
        resource_name="campaign", customer_id=customer_id, developer_token=developer_token, **service_account_config
    )
    schemas = get_schemas(cfg)

    assert "campaign" in schemas
    assert "ad_group" in schemas
    assert "ad" in schemas

    campaign = schemas["campaign"]
    assert campaign["id"].to_arrow_field() == pa.field("id", pa.int64())
    assert campaign["name"].to_arrow_field() == pa.field("name", pa.string())
    assert campaign["status"].to_arrow_field() == pa.field("status", pa.string())
    assert campaign["start_date"].to_arrow_field() == pa.field("start_date", pa.date32())

    ad_group = schemas["ad_group"]
    assert ad_group["id"].to_arrow_field() == pa.field("id", pa.int64())
    assert ad_group["name"].to_arrow_field() == pa.field("name", pa.string())
    assert ad_group["status"].to_arrow_field() == pa.field("status", pa.string())
    assert ad_group["type"].to_arrow_field() == pa.field("type", pa.string())
    assert ad_group["campaign"].to_arrow_field() == pa.field("campaign", pa.string())

    ad = schemas["ad"]
    assert ad["id"].to_arrow_field() == pa.field("id", pa.int64())
    assert ad["name"].to_arrow_field() == pa.field("name", pa.string())
    assert ad["type"].to_arrow_field() == pa.field("type", pa.string())
