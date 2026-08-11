import os

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.data_warehouse.backend import s3_proxy
from products.data_warehouse.backend.s3_proxy import (
    boto_proxy_config_kwargs,
    delta_proxy_storage_options,
    warehouse_bucket_host,
)

PROXY = "http://pod-name:x@egress-proxy.svc.cluster.local:4750/"
PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
NO_PROXY_ENV_VARS = ("NO_PROXY", "no_proxy")

BYPASS_ON = {
    "USE_LOCAL_SETUP": False,
    "BUCKET_URL": "s3://posthog-s3-datawarehouse-us-east-1/dlt",
    "DATA_WAREHOUSE_S3_REGION": "us-east-1",
}


def proxy_env(url: str | None, no_proxy: str | None = None) -> dict[str, str]:
    # Clear NO_PROXY too so the ambient env can't leak into proxy_excludes and make cases flaky.
    env = {**dict.fromkeys(PROXY_ENV_VARS, ""), **dict.fromkeys(NO_PROXY_ENV_VARS, "")}
    if url is not None:
        env["HTTPS_PROXY"] = url
    if no_proxy is not None:
        env["NO_PROXY"] = no_proxy
    return env


def flag(enabled: bool):
    return patch.object(s3_proxy.posthoganalytics, "feature_enabled", return_value=enabled)


class TestWarehouseS3ProxyBypass(SimpleTestCase):
    def setUp(self) -> None:
        # The flag result is cached per time bucket, so it has to be dropped between cases.
        s3_proxy._flag_enabled.cache_clear()

    @override_settings(**BYPASS_ON)
    def test_scopes_the_bypass_to_the_warehouse_bucket_host(self) -> None:
        with flag(True), patch.dict(os.environ, proxy_env(PROXY)):
            options = delta_proxy_storage_options()

        assert options["proxy_excludes"] == "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com"
        assert options["proxy_url"] == PROXY
        # Without virtual-hosted addressing the bucket isn't in the hostname, so the exclusion above
        # would have to name the shared regional endpoint, bypassing the proxy for all of S3. Both
        # spellings are set because delta-rs and object_store read different ones.
        assert options["AWS_S3_ADDRESSING_STYLE"] == "virtual"
        assert options["virtual_hosted_style_request"] == "true"

    @override_settings(**BYPASS_ON)
    def test_folds_the_environments_no_proxy_into_the_exclusions(self) -> None:
        # Setting proxy_url stops reqwest reading the env, dropping its NO_PROXY with it, so the
        # cluster's existing exemptions (here IMDS and in-cluster services) have to be carried over
        # or they would start transiting the proxy the moment the bypass turns on.
        with flag(True), patch.dict(os.environ, proxy_env(PROXY, no_proxy="169.254.169.254,.svc.cluster.local")):
            options = delta_proxy_storage_options()

        assert (
            options["proxy_excludes"]
            == "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com,169.254.169.254,.svc.cluster.local"
        )

    @override_settings(**BYPASS_ON)
    def test_bucket_host_follows_the_bucket_the_delta_tables_live_in(self) -> None:
        with override_settings(BUCKET_URL="s3://some-other-bucket/dlt", DATA_WAREHOUSE_S3_REGION="eu-central-1"):
            assert warehouse_bucket_host() == "some-other-bucket.s3.eu-central-1.amazonaws.com"

    @parameterized.expand(
        [
            ("local_setup", {"USE_LOCAL_SETUP": True}, True, PROXY),
            ("flag_off", {}, False, PROXY),
            ("region_unknown", {"DATA_WAREHOUSE_S3_REGION": ""}, True, PROXY),
            ("bucket_unknown", {"BUCKET_URL": ""}, True, PROXY),
            ("no_proxy_in_environment", {}, True, None),
        ]
    )
    def test_delta_options_are_empty_unless_everything_is_known(
        self, _name: str, settings_override: dict[str, object], flag_enabled: bool, proxy_url: str | None
    ) -> None:
        with (
            override_settings(**{**BYPASS_ON, **settings_override}),
            flag(flag_enabled),
            patch.dict(os.environ, proxy_env(proxy_url)),
        ):
            assert delta_proxy_storage_options() == {}

    @parameterized.expand(
        [
            ("enabled", {}, True, {"proxies": {}}),
            ("flag_off", {}, False, {}),
            ("local_setup", {"USE_LOCAL_SETUP": True}, True, {}),
        ]
    )
    def test_boto_clients_drop_the_proxy_only_when_the_bypass_is_on(
        self, _name: str, settings_override: dict[str, object], flag_enabled: bool, expected: dict[str, object]
    ) -> None:
        with override_settings(**{**BYPASS_ON, **settings_override}), flag(flag_enabled):
            assert boto_proxy_config_kwargs() == expected

    @override_settings(**BYPASS_ON)
    def test_boto_bypass_is_withheld_when_the_caller_supplies_an_endpoint(self) -> None:
        # A caller-supplied endpoint puts the host under the caller's control, so the proxy must stay
        # in front of it even with the bypass on, or a private-address S3-compatible source would be
        # dialed direct.
        with flag(True):
            assert boto_proxy_config_kwargs() == {"proxies": {}}
            assert boto_proxy_config_kwargs(endpoint_url="http://10.0.0.5/") == {}

    # A flags-service outage must not reroute production traffic on its own.
    @override_settings(**BYPASS_ON)
    def test_flag_evaluation_failure_leaves_traffic_on_the_proxy(self) -> None:
        with (
            patch.object(s3_proxy.posthoganalytics, "feature_enabled", side_effect=Exception("flags down")),
            patch.dict(os.environ, proxy_env(PROXY)),
        ):
            assert delta_proxy_storage_options() == {}

    # The options are rebuilt on every table open; evaluating the flag each time would put a network
    # call on that path.
    @override_settings(**BYPASS_ON)
    def test_flag_is_evaluated_once_per_interval_not_per_call(self) -> None:
        with flag(True) as evaluate, patch.dict(os.environ, proxy_env(PROXY)):
            for _ in range(5):
                delta_proxy_storage_options()

        assert evaluate.call_count == 1
