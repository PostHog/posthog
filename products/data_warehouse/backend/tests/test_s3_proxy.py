import os

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

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


class TestWarehouseS3ProxyBypass(SimpleTestCase):
    @override_settings(**BYPASS_ON)
    def test_scopes_the_bypass_to_the_warehouse_bucket_host(self) -> None:
        with patch.dict(os.environ, proxy_env(PROXY)):
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
        with patch.dict(os.environ, proxy_env(PROXY, no_proxy="169.254.169.254,.svc.cluster.local")):
            options = delta_proxy_storage_options()

        assert (
            options["proxy_excludes"]
            == "posthog-s3-datawarehouse-us-east-1.s3.us-east-1.amazonaws.com,169.254.169.254,.svc.cluster.local"
        )

    @override_settings(**BYPASS_ON)
    def test_bucket_host_follows_the_bucket_the_delta_tables_live_in(self) -> None:
        with override_settings(BUCKET_URL="s3://some-other-bucket/dlt", DATA_WAREHOUSE_S3_REGION="eu-central-1"):
            assert warehouse_bucket_host() == "some-other-bucket.s3.eu-central-1.amazonaws.com"

    @override_settings(**{**BYPASS_ON, "USE_LOCAL_SETUP": True})
    def test_delta_options_are_empty_for_a_local_setup(self) -> None:
        # The in-stack MinIO/SeaweedFS of USE_LOCAL_SETUP is addressed by raw host:port, not a real
        # DNS name, so neither addressing style nor the proxy bypass apply to it.
        with patch.dict(os.environ, proxy_env(PROXY)):
            assert delta_proxy_storage_options() == {}

    @parameterized.expand(
        [
            ("region_unknown", {"DATA_WAREHOUSE_S3_REGION": ""}, PROXY),
            ("bucket_unknown", {"BUCKET_URL": ""}, PROXY),
            ("no_proxy_in_environment", {}, None),
        ]
    )
    def test_proxy_options_are_absent_unless_the_bucket_host_and_proxy_are_both_known(
        self, _name: str, settings_override: dict[str, object], proxy_url: str | None
    ) -> None:
        with override_settings(**{**BYPASS_ON, **settings_override}), patch.dict(os.environ, proxy_env(proxy_url)):
            options = delta_proxy_storage_options()
        assert "proxy_url" not in options
        assert "proxy_excludes" not in options

    @override_settings(**BYPASS_ON)
    def test_addressing_style_is_forced_even_without_a_proxy(self) -> None:
        # Regression: addressing style used to be set only as a side effect of the proxy bypass
        # below, so a deployment with no egress proxy configured (e.g. a dedicated or self-hosted
        # install) fell back to delta-rs's path-style default and 403'd against a store that
        # requires virtual-hosted addressing (e.g. Alibaba OSS's "please use virtual hosted style to
        # access").
        with patch.dict(os.environ, proxy_env(None)):
            options = delta_proxy_storage_options()
        assert options["AWS_S3_ADDRESSING_STYLE"] == "virtual"
        assert options["virtual_hosted_style_request"] == "true"
        assert "proxy_url" not in options

    @parameterized.expand(
        [
            ("no_proxy", None),
            ("with_proxy", PROXY),
        ]
    )
    def test_addressing_style_stays_path_style_for_a_dotted_bucket_name(
        self, _name: str, proxy_url: str | None
    ) -> None:
        # Regression: AWS's wildcard TLS cert for its own S3 endpoints covers exactly one hostname
        # label, so a bucket name with a dot in it (e.g. "warehouse.example") produces a
        # virtual-hosted hostname with an extra label the cert doesn't cover, and forcing virtual
        # addressing there breaks certificate validation instead of fixing anything. Path-style
        # still works for it, so it must stay off the override - with or without a proxy configured.
        with (
            override_settings(**{**BYPASS_ON, "BUCKET_URL": "s3://warehouse.example/dlt"}),
            patch.dict(os.environ, proxy_env(proxy_url)),
        ):
            assert delta_proxy_storage_options() == {}

    @parameterized.expand(
        [
            ("deployed", {}, {"proxies": {}}),
            ("local_setup", {"USE_LOCAL_SETUP": True}, {}),
        ]
    )
    def test_boto_clients_drop_the_proxy_outside_local_setup(
        self, _name: str, settings_override: dict[str, object], expected: dict[str, object]
    ) -> None:
        with override_settings(**{**BYPASS_ON, **settings_override}):
            assert boto_proxy_config_kwargs() == expected

    @override_settings(**BYPASS_ON)
    def test_boto_bypass_is_withheld_when_the_caller_supplies_an_endpoint(self) -> None:
        # A caller-supplied endpoint puts the host under the caller's control, so the proxy must stay
        # in front of it even with the bypass on, or a private-address S3-compatible source would be
        # dialed direct.
        assert boto_proxy_config_kwargs() == {"proxies": {}}
        assert boto_proxy_config_kwargs(endpoint_url="http://10.0.0.5/") == {}
