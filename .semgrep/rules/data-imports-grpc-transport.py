# Test cases for data-imports-grpc-transport rules.
# These fixtures are matched against the rule patterns by `pytest .semgrep/`.
# ruff: noqa: F401, F841, E501
#
# `paths.include` in the rule scopes the matchers to
# `products/warehouse_sources/backend/temporal/data_imports/sources/**`, but for the test fixture the
# paths setting is ignored — semgrep applies the rule directly to this file.

import grpc
from grpc import RpcError, StatusCode

from google.ads.googleads.client import GoogleAdsClient
from google.cloud import bigquery_storage
from google.cloud.bigquery_storage import BigQueryReadClient


# ============================================================
# Should flag: raw grpc channels
# ============================================================


def bad_secure_channel():
    # ruleid: data-imports-grpc-transport-raw-channel
    return grpc.secure_channel("host:443", None)


def bad_insecure_channel():
    # ruleid: data-imports-grpc-transport-raw-channel
    return grpc.insecure_channel("host:443")


def bad_aio_secure_channel():
    # ruleid: data-imports-grpc-transport-raw-channel
    return grpc.aio.secure_channel("host:443", None)


def bad_aio_insecure_channel():
    # ruleid: data-imports-grpc-transport-raw-channel
    return grpc.aio.insecure_channel("host:443")


# ============================================================
# Should flag: BigQuery Storage read client
# ============================================================


def bad_bq_read_client_qualified(credentials):
    # ruleid: data-imports-grpc-transport-bigquery-read-client
    return bigquery_storage.BigQueryReadClient(credentials=credentials)


def bad_bq_read_client_bare(credentials):
    # ruleid: data-imports-grpc-transport-bigquery-read-client
    return BigQueryReadClient(credentials=credentials)


# ============================================================
# Should flag: Google Ads client construction
# ============================================================


def bad_google_ads_client(credentials):
    # ruleid: data-imports-grpc-transport-google-ads-client
    return GoogleAdsClient(credentials=credentials, developer_token="x")


def bad_google_ads_load_from_dict(config):
    # ruleid: data-imports-grpc-transport-google-ads-client
    return GoogleAdsClient.load_from_dict(config)


# ============================================================
# Should NOT flag: type and exception imports / handling
# ============================================================


def ok_status_code_use(code: StatusCode) -> None:
    pass


def ok_exception_handling():
    try:
        do_something()
    except RpcError:
        pass


def do_something() -> None:
    pass


# ============================================================
# Should NOT flag: the tracked transport (the supported paths)
# ============================================================


def ok_tracked_channel(channel):
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import make_tracked_channel

    return make_tracked_channel(channel, host="host")


def ok_tracked_interceptors(client):
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import tracked_interceptors

    return client.get_service("GoogleAdsService", interceptors=tracked_interceptors("host"))
