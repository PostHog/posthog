import io
import gzip
import json
from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from requests import Response
from urllib3.response import HTTPResponse

from posthog.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth, BearerTokenAuth, HttpBasicAuth
from posthog.temporal.data_imports.sources.custom.source import (
    MAX_MANIFEST_RESOURCES,
    PROBE_ERROR_SNIPPET_BYTES,
    PROBE_MAX_RESOURCES,
    CustomSource,
    FanoutChain,
    ManifestValidationError,
    _fanout_chain,
    _read_capped_text,
    _validate_resource_graph,
    manifest_request_hosts,
    validate_manifest_structure,
    validate_manifest_urls,
)
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from posthog.temporal.data_imports.util import NonRetryableException

from products.data_warehouse.backend.types import IncrementalFieldType


def validate_manifest(manifest: Any) -> None:
    # Full-validation composite (structure + graph). Production runs the two
    # levels separately — permissive structural checks on stored-manifest
    # reads, graph rules on the API validation paths — so the composite lives
    # here with the tests that use it.
    validate_manifest_structure(manifest)
    _validate_resource_graph(manifest)


def _minimal_manifest(base_url: str = "https://api.example.com") -> dict:
    """A structurally valid manifest. Auth carries no inline credential — the
    secret lives in the separate auth_* config fields."""
    return {
        "client": {
            "base_url": base_url,
            "auth": {"type": "bearer"},
        },
        "resources": [
            {
                "name": "users",
                "primary_key": "id",
                "endpoint": {"path": "/users", "data_selector": "data"},
            }
        ],
    }


class TestValidateManifest(SimpleTestCase):
    def test_accepts_minimal_manifest(self):
        validate_manifest(_minimal_manifest())

    @parameterized.expand(
        [
            ("not a dict", "must be a JSON object"),
            ({}, "Field required"),
            (
                {"client": {"base_url": "https://x"}, "resources": []},
                "at least 1",
            ),
            ({"client": {}, "resources": [{}]}, "base_url"),
            (
                {"client": {"base_url": "x"}, "resources": [{"name": "users"}]},
                "endpoint",
            ),
        ]
    )
    def test_rejects_malformed(self, manifest, expected_substring):
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert expected_substring in str(ctx.exception)

    def test_rejects_duplicate_resource_names(self):
        manifest = _minimal_manifest()
        manifest["resources"].append({**manifest["resources"][0]})
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "Duplicate" in str(ctx.exception)

    def test_rejects_too_many_resources(self):
        # An unbounded resource count turns the create-time probe into an outbound
        # request amplifier — the manifest is capped at MAX_MANIFEST_RESOURCES.
        manifest = _minimal_manifest()
        manifest["resources"] = [
            {"name": f"r{i}", "endpoint": {"path": f"/r{i}"}} for i in range(MAX_MANIFEST_RESOURCES + 1)
        ]
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "at most" in str(ctx.exception)

    def test_accepts_resource_count_at_limit(self):
        manifest = _minimal_manifest()
        manifest["resources"] = [
            {"name": f"r{i}", "endpoint": {"path": f"/r{i}"}} for i in range(MAX_MANIFEST_RESOURCES)
        ]
        validate_manifest(manifest)

    def test_rejects_unknown_auth_type(self):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "oauth"}
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "auth.type" in str(ctx.exception)

    @parameterized.expand(["TRACE", "PUT", "PATCH", "DELETE"])
    def test_rejects_non_read_http_method(self, method):
        # A sync only fetches — GET and POST are the only accepted methods;
        # write verbs must be rejected so a manifest can't mutate upstream data.
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["method"] = method
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "method" in str(ctx.exception)

    @parameterized.expand(["GET", "POST", "get", "post"])
    def test_accepts_read_http_method(self, method):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["method"] = method
        validate_manifest(manifest)

    def test_accepts_endpoint_params_and_json_body(self):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"] = {
            "path": "/search",
            "method": "POST",
            "params": {"limit": 100},
            "json": {"query": "foo"},
        }
        validate_manifest(manifest)

    @parameterized.expand([("json", ["not", "an", "object"]), ("params", ["nope"])])
    def test_rejects_non_object_params_or_json(self, field, value):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"][field] = value
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert field in str(ctx.exception)

    @parameterized.expand(
        [
            ("token", {"type": "bearer", "token": "leaked"}),
            ("api_key", {"type": "api_key", "api_key": "leaked"}),
            ("password", {"type": "http_basic", "username": "alice", "password": "leaked"}),
        ]
    )
    def test_rejects_inline_credentials(self, _name, auth):
        # Credentials belong in the dedicated secret auth_* fields, never inline
        # in the manifest — the manifest field is non-secret and round-trips to the client.
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "must not be embedded" in str(ctx.exception)


class TestValidateManifestUrls(SimpleTestCase):
    @parameterized.expand(
        [
            ("http_127", "http://127.0.0.1/api"),
            ("https_loopback", "https://127.0.0.1/api"),
            ("https_private", "https://10.0.0.1/api"),
            ("https_imds", "https://169.254.169.254/latest/meta-data/"),
            ("http_public", "http://api.example.com"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_rejects_unsafe_or_http(self, _name: str, base_url: str):
        manifest = _minimal_manifest(base_url=base_url)
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok, err

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch(
        "posthog.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda host, team_id: (host != "127.0.0.1", None if host != "127.0.0.1" else "blocked"),
    )
    def test_rejects_absolute_resource_path_when_internal(self, _mock):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["path"] = "http://127.0.0.1/leak"
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "users" in (err or "")

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch(
        "posthog.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda host, team_id: (host != "127.0.0.1", None if host != "127.0.0.1" else "blocked"),
    )
    def test_rejects_whitespace_prefixed_internal_path(self, _mock):
        # A leading space makes the raw `startswith` check miss the absolute URL, but urljoin
        # strips it and the sync reaches 127.0.0.1 — the validator must resolve it the same way.
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["path"] = " https://127.0.0.1/leak"
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "users" in (err or "")

    @parameterized.expand(
        [
            ("http_public", "http://api.example.com"),
            ("http_private", "http://10.0.0.1/api"),
            ("https_loopback", "https://127.0.0.1/api"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="")
    def test_self_hosted_skips_host_check(self, _name: str, base_url: str):
        # _is_host_safe is a no-op outside of cloud, and http:// is permitted.
        # A self-hosted instance must be able to reach internal/private hosts.
        manifest = _minimal_manifest(base_url=base_url)
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert ok, err


class TestCustomSourceAssembleManifest(SimpleTestCase):
    def test_rejects_invalid_json(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        with self.assertRaises(ManifestValidationError):
            source._assemble_manifest(config)

    def test_returns_parsed_manifest(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        manifest = source._assemble_manifest(config)
        assert manifest["client"]["base_url"] == "https://api.example.com"

    @parameterized.expand(
        [
            ("bearer", {"type": "bearer"}, {"auth_token": "ya29.secret"}, "token", "ya29.secret"),
            (
                "api_key",
                {"type": "api_key", "name": "X-API-Key", "location": "header"},
                {"auth_api_key": "sk_test"},
                "api_key",
                "sk_test",
            ),
            (
                "http_basic",
                {"type": "http_basic", "username": "alice"},
                {"auth_password": "hunter2"},
                "password",
                "hunter2",
            ),
        ]
    )
    def test_injects_auth_secret_for_type(self, _name, auth, secret_kwargs, expected_key, expected_value):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), **secret_kwargs)
        assembled = source._assemble_manifest(config)
        assert assembled["client"]["auth"][expected_key] == expected_value

    def test_leaves_auth_alone_when_no_secret_provided(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        assembled = source._assemble_manifest(config)
        assert "token" not in assembled["client"]["auth"]


class TestCustomSourceGetSchemas(SimpleTestCase):
    def test_returns_one_schema_per_resource(self):
        manifest = _minimal_manifest()
        manifest["resources"].append(
            {
                "name": "orders",
                "primary_key": ["order_id", "line_no"],
                "endpoint": {
                    "path": "/orders",
                    "data_selector": "data",
                    "incremental": {"cursor_path": "updated_at", "start_param": "since"},
                },
            }
        )
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schemas = source.get_schemas(config, team_id=999)
        assert {s.name for s in schemas} == {"users", "orders"}

        orders = next(s for s in schemas if s.name == "orders")
        assert orders.supports_incremental
        assert orders.incremental_fields[0]["field"] == "updated_at"
        assert orders.detected_primary_keys == ["order_id", "line_no"]

    def test_filters_by_names(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        schemas = source.get_schemas(config, team_id=999, names=["nonexistent"])
        assert schemas == []

    @parameterized.expand(
        [
            ("default_datetime", None, IncrementalFieldType.DateTime),
            ("declared_integer", "integer", IncrementalFieldType.Integer),
            ("unknown_falls_back", "bogus", IncrementalFieldType.DateTime),
        ]
    )
    def test_incremental_cursor_type_from_manifest(self, _name, declared, expected):
        manifest = _minimal_manifest()
        incremental: dict = {"cursor_path": "cursor"}
        if declared is not None:
            incremental["cursor_type"] = declared
        manifest["resources"][0]["endpoint"]["incremental"] = incremental

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schema = source.get_schemas(config, team_id=999)[0]
        assert schema.incremental_fields[0]["type"] == expected
        assert schema.incremental_fields[0]["field_type"] == expected


class TestCustomSourceValidateCredentials(SimpleTestCase):
    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_true_on_2xx(self, mock_session):
        response = MagicMock(status_code=200, text="{}")
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert err is None

    @parameterized.expand([401, 403])
    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_false_on_auth_rejection(self, status_code, mock_session):
        response = MagicMock(status_code=status_code, text="unauthorized")
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert str(status_code) in (err or "")

    @parameterized.expand([404, 405, 429, 500])
    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_non_auth_error_status_does_not_block_creation(self, status_code, mock_session):
        # A 404/405/429/5xx is not a credential problem — it must not block
        # source creation; the real sync surfaces it if it persists.
        mock_session.return_value.request.return_value = MagicMock(status_code=status_code, text="nope")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probes_resources_until_auth_failure(self, mock_session):
        # A later (within-cap) resource fails auth — validation must catch it, not stop at the first.
        manifest = _minimal_manifest()
        manifest["resources"].append({"name": "orders", "endpoint": {"path": "/orders"}})
        mock_session.return_value.request.side_effect = [
            MagicMock(status_code=200),
            MagicMock(status_code=403),
        ]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "orders" in (err or "")
        assert "403" in (err or "")

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_caps_resource_count(self, mock_session):
        # The probe must hit at most PROBE_MAX_RESOURCES upstreams regardless of how many
        # resources the manifest declares — so the endpoint can't fan out one request per resource.
        manifest = _minimal_manifest()
        manifest["resources"] = [
            {"name": f"r{i}", "endpoint": {"path": f"/r{i}"}} for i in range(PROBE_MAX_RESOURCES + 3)
        ]
        mock_session.return_value.request.return_value = MagicMock(status_code=200)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_count == PROBE_MAX_RESOURCES

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_streams_and_caps_error_body(self, mock_session):
        # The probe opens responses with stream=True and reads only a bounded slice
        # of a 401/403 body for the error snippet — never buffering the full body.
        response = MagicMock(status_code=403)
        response.raw.read.return_value = b"forbidden: token expired"
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        # The snippet came from the bounded raw read; had the code used response.text[:200]
        # the message would contain a MagicMock repr instead of the decoded bytes.
        assert "forbidden: token expired" in (err or "")
        assert mock_session.return_value.request.call_args.kwargs["stream"] is True
        response.close.assert_called_once()

    def test_read_capped_text_is_decompression_bomb_proof(self):
        # A gzip body that inflates ~1000x must not be materialized — reading the raw
        # (undecoded) stream caps the snippet regardless of Content-Encoding.
        payload = b"\x00" * (20 * 1024 * 1024)
        compressed = gzip.compress(payload)
        assert len(payload) / len(compressed) > 100  # it really is a decompression bomb

        response = MagicMock()
        response.raw = HTTPResponse(
            body=io.BytesIO(compressed),
            headers={"content-encoding": "gzip", "content-length": str(len(compressed))},
            status=403,
            preload_content=False,
        )
        snippet = _read_capped_text(response)
        assert len(snippet) <= PROBE_ERROR_SNIPPET_BYTES

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_attaches_query_location_api_key(self, mock_session):
        # An api_key with location 'query' must reach the probe request — the
        # probe builds auth via create_auth, the same path the real sync uses.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "api_key", "name": "apikey", "location": "query"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_api_key="sk_test")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        probe_auth = mock_session.return_value.request.call_args.kwargs["auth"]
        assert isinstance(probe_auth, APIKeyAuth)
        assert probe_auth.location == "query"
        assert probe_auth.api_key == "sk_test"

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_replays_json_body(self, mock_session):
        # A POST endpoint with a JSON body must send that body in the probe, so
        # an endpoint that needs it doesn't answer differently at probe vs sync.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"] = {"path": "/search", "method": "POST", "json": {"query": "foo"}}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_args.kwargs["json"] == {"query": "foo"}

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_replays_static_query_params(self, mock_session):
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["params"] = {"limit": 100, "order": "asc"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_args.kwargs["params"] == {"limit": 100, "order": "asc"}

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_skips_incremental_param_specs(self, mock_session):
        # Dict-valued params are the engine's incremental/resolver specs, resolved
        # against cursor state at sync time — the probe has none, so it forwards
        # only the plain scalar params and drops the spec.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["params"] = {
            "limit": 100,
            "since": {"type": "incremental", "cursor_path": "updated_at", "initial_value": "2020-01-01"},
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_args.kwargs["params"] == {"limit": 100}

    @parameterized.expand(
        [
            (
                "bearer",
                {"type": "bearer"},
                {"auth_token": "ya29.secret"},
                BearerTokenAuth,
                {"token": "ya29.secret"},
            ),
            (
                "api_key_header",
                {"type": "api_key", "name": "X-API-Key", "location": "header"},
                {"auth_api_key": "sk_h"},
                APIKeyAuth,
                {"api_key": "sk_h", "location": "header", "name": "X-API-Key"},
            ),
            (
                "api_key_cookie",
                {"type": "api_key", "name": "session", "location": "cookie"},
                {"auth_api_key": "sk_c"},
                APIKeyAuth,
                {"api_key": "sk_c", "location": "cookie", "name": "session"},
            ),
            (
                "api_key_param",
                {"type": "api_key", "name": "key", "location": "param"},
                {"auth_api_key": "sk_p"},
                APIKeyAuth,
                {"api_key": "sk_p", "location": "param", "name": "key"},
            ),
            (
                "http_basic",
                {"type": "http_basic", "username": "alice"},
                {"auth_password": "hunter2"},
                HttpBasicAuth,
                {"username": "alice", "password": "hunter2"},
            ),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_attaches_auth_for_each_type(
        self, _name, auth_manifest, secret_kwargs, expected_cls, expected_attrs, mock_session
    ):
        # Every supported (auth type, location) combination must reach the probe
        # request via create_auth — the same code path the real sync uses.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth_manifest

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), **secret_kwargs)
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        probe_auth = mock_session.return_value.request.call_args.kwargs["auth"]
        assert isinstance(probe_auth, expected_cls)
        for attr, expected in expected_attrs.items():
            assert getattr(probe_auth, attr) == expected, f"{attr} mismatch"

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_registers_credential_for_redaction(self, mock_session):
        # The secret must be handed to the tracked session as a redact value so
        # it's masked from logs/samples even when injected into a query param
        # whose name the denylist scrubber can't anticipate.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "api_key", "name": "subscription-key", "location": "query"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_api_key="sk_live_leaky")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        assert mock_session.call_args.kwargs["redact_values"] == ("sk_live_leaky",)

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_false_on_network_error(self, mock_session):
        # A connection-level failure (DNS, TLS, timeout) must surface as a
        # credential validation error pointing at the offending resource.
        mock_session.return_value.request.side_effect = ConnectionError("boom")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "could not reach" in (err or "")
        assert "users" in (err or "")

    def test_returns_false_on_invalid_manifest(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert err is not None


class TestManifestRequestHosts(SimpleTestCase):
    def _manifest(self, base_url: str, resource_paths: list[str]) -> str:
        return json.dumps(
            {
                "client": {"base_url": base_url},
                "resources": [{"name": f"r{i}", "endpoint": {"path": p}} for i, p in enumerate(resource_paths)],
            }
        )

    def test_base_url_host(self):
        assert manifest_request_hosts(self._manifest("https://api.example.com/v1", ["/users"])) == frozenset(
            {"api.example.com"}
        )

    def test_absolute_resource_paths_add_hosts(self):
        # Relative paths inherit base_url's host; only absolute URLs introduce a new host.
        manifest = self._manifest("https://api.example.com", ["/users", "https://cdn.other.net/data"])
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "cdn.other.net"})

    def test_path_param_absolute_url_is_collected(self):
        # A scalar param bound into a "{placeholder}" becomes the request URL at sync time
        # (_bind_path_params), so its host must be tracked even though the literal path is relative.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {
                        "name": "r",
                        "endpoint": {"path": "{target}", "params": {"target": "https://attacker.example.net/"}},
                    }
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_path_param_split_scheme_is_resolved(self):
        # The absolute URL is split across the template and a param ("{scheme}://host" +
        # {"scheme": "https"}); neither piece is a URL on its own, but the bound path is.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {
                        "name": "r",
                        "endpoint": {"path": "{scheme}://attacker.example.net/data", "params": {"scheme": "https"}},
                    }
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_uppercase_scheme_absolute_path_adds_host(self):
        # urljoin treats `HTTPS://host` as absolute (schemes are case-insensitive), so a
        # mixed-case scheme must still register the new host — otherwise an editor who can't
        # read the stored secret could retarget the preserved credential past the re-entry gate.
        manifest = self._manifest("https://api.example.com", ["HTTPS://attacker.example.net/data"])
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_uppercase_scheme_split_across_param_adds_host(self):
        # Same retarget bypass via a split scheme: "{scheme}://host" + {"scheme": "HTTPS"}.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {
                        "name": "r",
                        "endpoint": {"path": "{scheme}://attacker.example.net/data", "params": {"scheme": "HTTPS"}},
                    }
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    @parameterized.expand(
        [
            ("leading_space", " https://attacker.example.net/data"),
            ("leading_tab", "\thttps://attacker.example.net/data"),
            ("leading_newline", "\nhttps://attacker.example.net/data"),
            ("leading_nul", "\x00https://attacker.example.net/data"),
            ("leading_space_uppercase", " HTTPS://attacker.example.net/data"),
        ]
    )
    def test_whitespace_prefixed_absolute_path_adds_host(self, _name, path):
        # urljoin strips leading whitespace/control chars before parsing the scheme, so the
        # sync requests attacker.example.net while a raw `startswith` check sees no new host —
        # the retarget guard must resolve the path the same way the engine does.
        manifest = self._manifest("https://api.example.com", [path])
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_url_param_not_referenced_in_path_is_ignored(self):
        # A URL-valued query param that isn't a path placeholder is a normal query value, not a
        # request destination — it must not be counted (avoids false re-entry prompts).
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {"name": "r", "endpoint": {"path": "/users", "params": {"callback": "https://other.net/"}}}
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com"})

    def test_backslash_authority_resolves_to_real_host(self):
        # `https://evil\@trusted/` connects to `evil` (urllib3/WHATWG) even though urlparse
        # alone reads `trusted` — the guard must see the real destination, not be fooled.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://attacker.example.net\\@api.example.com/"},
                "resources": [{"name": "r", "endpoint": {"path": "/users"}}],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"attacker.example.net"})

    def test_host_is_lowercased(self):
        assert manifest_request_hosts(self._manifest("https://API.Example.COM", [])) == frozenset({"api.example.com"})

    @parameterized.expand([("not json", "{nope}"), ("non_string", 123), ("none", None), ("json_array", "[1, 2]")])
    def test_unparseable_returns_empty(self, _name, raw):
        assert manifest_request_hosts(raw) == frozenset()


class TestCustomSourceSourceForPipeline(SimpleTestCase):
    def test_invalid_manifest_raises_non_retryable(self):
        # A permanent config error must fail fast, not burn the Temporal retry budget.
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, MagicMock(team_id=999))

    def test_missing_resource_raises_non_retryable(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        inputs = MagicMock(team_id=999, schema_name="nonexistent")
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @parameterized.expand(
        [("default_asc", None, "asc"), ("explicit_asc", "asc", "asc"), ("explicit_desc", "desc", "desc")]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_sort_mode_threaded_to_source_response(self, _name, declared, expected, mock_resources):
        mock_resources.return_value = [_fake_resource("users")]
        manifest = _minimal_manifest()
        if declared is not None:
            manifest["resources"][0]["sort_mode"] = declared

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)
        assert response.sort_mode == expected

    @parameterized.expand(
        [
            ("opted_in", True, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            ("opted_out_drops_value", False, "2024-01-01T00:00:00Z", None),
            ("opted_in_none", True, None, None),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_incremental_last_value_threaded_to_rest_engine(
        self, _name, should_use_incremental, last_value, expected, mock_resources
    ):
        # The high-watermark must only reach the REST engine when the schema is
        # configured for incremental sync — otherwise a full refresh would skip rows.
        mock_resources.return_value = [_fake_resource("users")]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=last_value,
        )
        source.source_for_pipeline(config, inputs)

        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] == expected

    @parameterized.expand(
        [
            ("auto", {"type": "auto"}),
            ("single_page", {"type": "single_page"}),
            ("json_response", {"type": "json_response", "next_url_path": "next"}),
            ("header_link", {"type": "header_link"}),
            ("cursor", {"type": "cursor", "cursor_path": "next_cursor", "cursor_param": "cursor"}),
            ("offset", {"type": "offset", "limit": 100}),
            ("page_number", {"type": "page_number", "page_param": "page"}),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_paginator_config_threaded_to_rest_engine(self, _name, paginator_config, mock_resources):
        # Every PaginatorType the REST engine knows about must round-trip through
        # the custom source — paginator config is passed through untouched and the
        # REST engine selects the paginator at sync time.
        mock_resources.return_value = [_fake_resource("users")]
        manifest = _minimal_manifest()
        manifest["client"]["paginator"] = paginator_config

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        source.source_for_pipeline(config, inputs)

        threaded_config = mock_resources.call_args.args[0]
        assert threaded_config["client"]["paginator"] == paginator_config

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_cursor_type_stripped_before_rest_engine(self, mock_resources):
        # cursor_type informs schema field typing but is not a valid kwarg for the
        # engine's Incremental(**config) — it must be removed before the manifest
        # reaches the REST engine, while the other incremental keys survive.
        mock_resources.return_value = [_fake_resource("users")]
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["incremental"] = {
            "cursor_path": "updated_at",
            "start_param": "since",
            "cursor_type": "integer",
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        source.source_for_pipeline(config, inputs)

        threaded_incremental = mock_resources.call_args.args[0]["resources"][0]["endpoint"]["incremental"]
        assert threaded_incremental == {"cursor_path": "updated_at", "start_param": "since"}


def _fanout_manifest() -> dict:
    """A parent (`forms`) + fan-out child (`responses`) that binds the parent's
    `id` into its path via a `type: "resolve"` param."""
    return {
        "client": {"base_url": "https://api.example.com", "auth": {"type": "bearer"}},
        "resources": [
            {"name": "forms", "primary_key": "id", "endpoint": {"path": "/forms", "data_selector": "items"}},
            {
                "name": "responses",
                "primary_key": "token",
                "endpoint": {
                    "path": "/forms/{form_id}/responses",
                    "data_selector": "items",
                    "params": {"form_id": {"type": "resolve", "resource": "forms", "field": "id"}},
                },
            },
        ],
    }


def _fake_resource(name: str) -> MagicMock:
    # MagicMock(name=...) sets the mock's repr, not a `.name` attribute, so the
    # source's `r.name == chosen_name` lookup needs the attribute set explicitly.
    resource = MagicMock()
    resource.name = name
    return resource


def _break_unknown_parent(m: dict) -> None:
    m["resources"][1]["endpoint"]["params"]["form_id"]["resource"] = "nonexistent"


def _break_resolve_not_in_path(m: dict) -> None:
    # Resolve param with no matching `{placeholder}` — the engine can only inject into the path.
    m["resources"][1]["endpoint"]["path"] = "/responses"


def _break_cycle(m: dict) -> None:
    # Make `forms` depend on `responses`, closing a loop.
    m["resources"][0]["endpoint"]["path"] = "/forms/{response_token}"
    m["resources"][0]["endpoint"]["params"] = {
        "response_token": {"type": "resolve", "resource": "responses", "field": "token"}
    }


def _break_multiple_resolve_params(m: dict) -> None:
    m["resources"][1]["endpoint"]["path"] = "/forms/{form_id}/responses/{other_id}"
    m["resources"][1]["endpoint"]["params"]["other_id"] = {"type": "resolve", "resource": "forms", "field": "id"}


def _break_missing_resolve_field(m: dict) -> None:
    # The engine raises KeyError (not ValueError) for this shape — it must still
    # surface as a clean validation error, not a 500.
    del m["resources"][1]["endpoint"]["params"]["form_id"]["field"]


def _break_missing_resolve_resource(m: dict) -> None:
    del m["resources"][1]["endpoint"]["params"]["form_id"]["resource"]


def _break_invalid_resolve_field_jsonpath(m: dict) -> None:
    # The resolve field is a JSONPath; a malformed one raises a bare-Exception
    # subclass (JsonPathParserError) from inside the engine.
    m["resources"][1]["endpoint"]["params"]["form_id"]["field"] = "user..["


def _break_path_starting_with_placeholder(m: dict) -> None:
    # A child path that BEGINS with the parent placeholder lets an absolute URL
    # in the parent's field move the authenticated request off base_url.
    m["resources"][1]["endpoint"]["path"] = "{form_id}/responses"


def _break_leading_slash_placeholder(m: dict) -> None:
    # A leading slash is NOT a defense: the engine strips leading slashes before
    # joining onto base_url, so `/{form_id}/...` still resolves to whatever host
    # the bound parent value carries.
    m["resources"][1]["endpoint"]["path"] = "/{form_id}/responses"


def _break_scheme_prefixed_placeholder(m: dict) -> None:
    # A literal scheme prefix lets the placeholder supply the URL's authority:
    # `https:{form_id}/...` with `form_id="//attacker/x"` formats to
    # `https://attacker/x/...`, an absolute URL off base_url. The placeholder is
    # not the first path segment, so a position-only guard misses it.
    m["resources"][1]["endpoint"]["path"] = "https:{form_id}/responses"


def _add_nested_child(m: dict) -> None:
    # Grandchild: nesting is capped at one level — a parent must be top-level.
    m["resources"].append(
        {
            "name": "answers",
            "primary_key": "id",
            "endpoint": {
                "path": "/responses/{response_token}/answers",
                "params": {"response_token": {"type": "resolve", "resource": "responses", "field": "token"}},
            },
        }
    )


class TestCustomSourceFanoutValidation(SimpleTestCase):
    def test_accepts_valid_fanout(self):
        validate_manifest(_fanout_manifest())

    @parameterized.expand(
        [
            ("unknown_parent", _break_unknown_parent),
            ("resolve_param_not_bound_in_path", _break_resolve_not_in_path),
            ("cycle", _break_cycle),
            ("multiple_resolve_params", _break_multiple_resolve_params),
            ("missing_resolve_field", _break_missing_resolve_field),
            ("missing_resolve_resource", _break_missing_resolve_resource),
            ("invalid_resolve_field_jsonpath", _break_invalid_resolve_field_jsonpath),
            ("nested_child", _add_nested_child),
            ("path_starting_with_placeholder", _break_path_starting_with_placeholder),
            ("leading_slash_placeholder", _break_leading_slash_placeholder),
            ("scheme_prefixed_placeholder", _break_scheme_prefixed_placeholder),
        ]
    )
    def test_rejects_invalid_fanout(self, _name, break_manifest):
        # Every fan-out misconfiguration the engine's dependency graph rejects must
        # surface at manifest-validation time, not first sync.
        manifest = _fanout_manifest()
        break_manifest(manifest)
        with self.assertRaises(ManifestValidationError):
            validate_manifest(manifest)

    @parameterized.expand(
        [
            # str(graphlib.CycleError) is its raw args tuple — the user-facing
            # message must render the cycle, not the tuple repr.
            ("cycle", _break_cycle, ["dependency cycle"]),
            # The nesting cap must name the offending resources.
            ("nested_child", _add_nested_child, ["'answers'", "'responses'", "one level of nesting"]),
            # The placeholder-authority guard must name the resource and point at
            # the scheme-prefix escape, not just the leading-segment case.
            ("scheme_prefixed_placeholder", _break_scheme_prefixed_placeholder, ["'responses'", "scheme", "redirect"]),
        ]
    )
    def test_rejection_message_is_readable(self, _name, break_manifest, expected_fragments):
        manifest = _fanout_manifest()
        break_manifest(manifest)
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        message = str(ctx.exception)
        assert not message.startswith("(")
        for fragment in expected_fragments:
            assert fragment in message

    @parameterized.expand(
        [
            # Graph rules apply on every validation path — create/update ...
            ("create_or_update", {}),
            # ... and schema-scoped read checks against stored config alike.
            # Builder-authored manifests are always graph-valid, so a stored
            # manifest tripping this was hand-authored JSON that never synced.
            ("schema_scoped_read_check", {"schema_name": "forms"}),
        ]
    )
    def test_validate_credentials_rejects_broken_graph(self, _name, kwargs):
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999, **kwargs)
        assert ok is False
        assert err is not None and "nonexistent" in err


class TestFanoutChain(SimpleTestCase):
    def test_top_level_resource_has_no_ancestors(self):
        manifest = _fanout_manifest()
        chain = _fanout_chain(manifest, "forms")
        assert chain == FanoutChain(ancestors=[], child=manifest["resources"][0])
        assert chain.is_fanout_child is False

    def test_child_chain_is_parent_first(self):
        manifest = _fanout_manifest()
        parent, child = manifest["resources"]
        chain = _fanout_chain(manifest, "responses")
        assert chain == FanoutChain(ancestors=[parent], child=child)
        assert chain.is_fanout_child is True

    def test_multi_level_chain(self):
        # Create-time validation rejects nesting beyond one level, but the sync
        # path must still walk a deeper chain correctly if a stored manifest
        # carries one (e.g. written before the cap existed).
        manifest = _fanout_manifest()
        _add_nested_child(manifest)
        forms, responses, answers = manifest["resources"]
        assert _fanout_chain(manifest, "answers") == FanoutChain(ancestors=[forms, responses], child=answers)

    @patch("posthog.temporal.data_imports.sources.custom.source.logger")
    def test_falls_back_to_chosen_when_unrelated_resource_breaks_the_graph(self, mock_logger):
        # A stored manifest can predate the create-time graph rules. A graph
        # error on a sibling must not sink this schema — the chain degrades to
        # the pre-fan-out single-resource behavior, and the degradation is
        # logged so the affected population stays measurable.
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)
        manifest["resources"].append(
            {"name": "users", "primary_key": "id", "endpoint": {"path": "/users", "data_selector": "items"}}
        )
        assert _fanout_chain(manifest, "users") == FanoutChain(ancestors=[], child=manifest["resources"][2])
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.args[0] == "custom_source_fanout_graph_fallback"
        assert mock_logger.warning.call_args.kwargs["schema_name"] == "users"

    def test_raises_for_chosen_resource_in_a_cycle(self):
        # The graph builder itself doesn't reject cycles (only create-time
        # static_order does) — the walk must fail loudly, not loop or truncate.
        manifest = _fanout_manifest()
        _break_cycle(manifest)
        with self.assertRaises(ValueError):
            _fanout_chain(manifest, "responses")


class TestCustomSourceFanoutPipeline(SimpleTestCase):
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_child_schema_runs_parent_and_child(self, mock_resources):
        # Selecting the child must hand the engine BOTH resources (parent first)
        # and return only the child resource — the parent is fetched transiently.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        threaded_resources = mock_resources.call_args.args[0]["resources"]
        assert [r["name"] for r in threaded_resources] == ["forms", "responses"]
        assert cast(Any, response.items()).name == "responses"
        assert response.primary_keys == ["token"]

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_top_level_schema_runs_only_that_resource(self, mock_resources):
        # A parent selected on its own is a one-element chain — only that resource
        # reaches the engine (no ancestors), and it's returned by name.
        mock_resources.return_value = [_fake_resource("forms")]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()))
        inputs = MagicMock(
            team_id=999,
            schema_name="forms",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        assert [r["name"] for r in mock_resources.call_args.args[0]["resources"]] == ["forms"]
        assert cast(Any, response.items()).name == "forms"

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_strips_incremental_from_parent_but_keeps_child(self, mock_resources):
        # The run's high-watermark belongs to the child; applying it to the parent
        # would silently drop parents (and their children). Parent must full-scan.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        manifest["resources"][0]["endpoint"]["incremental"] = {"cursor_path": "updated_at", "start_param": "since"}
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        source.source_for_pipeline(config, inputs)

        parent_cfg, child_cfg = mock_resources.call_args.args[0]["resources"]
        assert "incremental" not in parent_cfg["endpoint"]
        assert child_cfg["endpoint"]["incremental"] == {"cursor_path": "submitted_at", "start_param": "since"}
        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_strips_cursor_type_from_child(self, mock_resources):
        # cursor_type is a schema-typing hint the engine's Incremental(**config)
        # rejects — it must be removed before the child reaches the engine.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        manifest["resources"][1]["endpoint"]["incremental"] = {
            "cursor_path": "submitted_at",
            "start_param": "since",
            "cursor_type": "datetime",
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        source.source_for_pipeline(config, inputs)

        _parent_cfg, child_cfg = mock_resources.call_args.args[0]["resources"]
        assert child_cfg["endpoint"]["incremental"] == {"cursor_path": "submitted_at", "start_param": "since"}

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_strips_params_style_incremental_from_parent(self, mock_resources):
        # The engine also builds an incremental tracker from a params-style
        # {"type": "incremental"} spec — it must be stripped from ancestors too,
        # or the child's watermark would be injected as the parent's start param.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        manifest["resources"][0]["endpoint"]["params"] = {
            "since": {"type": "incremental", "cursor_path": "updated_at"},
            "status": "active",
        }
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        source.source_for_pipeline(config, inputs)

        parent_cfg, _child_cfg = mock_resources.call_args.args[0]["resources"]
        # Static params survive; only the incremental spec is removed.
        assert parent_cfg["endpoint"]["params"] == {"status": "active"}

    @parameterized.expand(
        [
            # Child with no declared sort_mode -> forced "desc".
            ("child_default", "responses", None, "desc"),
            # Child that explicitly declares "asc" -> STILL forced "desc". This is
            # the override that matters: per-batch asc commits on a child would
            # advance the watermark past later parents' older rows and skip them.
            ("child_overrides_declared_asc", "responses", "asc", "desc"),
            # Top-level resource keeps its declaration (default "asc").
            ("parent_keeps_declared", "forms", None, "asc"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_child_forces_deferred_watermark_sort_mode(
        self, _name, schema_name, declared_sort_mode, expected, mock_resources
    ):
        # Fan-out child rows arrive grouped per parent, never globally
        # cursor-ascending, so the "asc" per-batch watermark commit would skip
        # later parents' older rows after an interruption — children must always
        # use the deferred-commit ("desc") behavior.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        if declared_sort_mode is not None:
            next(r for r in manifest["resources"] if r["name"] == schema_name)["sort_mode"] = declared_sort_mode
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name=schema_name,
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)
        assert response.sort_mode == expected

    def test_engine_config_error_raises_non_retryable(self):
        # include_from_parent without a resolve param passes create-time graph
        # validation but is rejected by the engine at build time — a deterministic
        # config error that must not burn the Temporal retry budget.
        manifest = _minimal_manifest()
        manifest["resources"][0]["include_from_parent"] = ["id"]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_broken_sibling_does_not_sink_healthy_schema_sync(self, mock_resources):
        # A stored manifest can carry a graph-broken resource from before the
        # create-time rules existed — its healthy schemas must keep syncing.
        mock_resources.return_value = [_fake_resource("forms")]
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="forms",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        assert [r["name"] for r in mock_resources.call_args.args[0]["resources"]] == ["forms"]
        assert cast(Any, response.items()).name == "forms"

    def test_broken_sibling_fails_child_schema_fast(self):
        # Accepted trade-off: a child schema can't be built without the graph,
        # so when an UNRELATED resource breaks the graph, the fallback hands the
        # engine just the child, whose orphaned resolve param the engine rejects
        # at build time — a loud, non-retryable failure rather than wrong data.
        # (Top-level siblings keep syncing; see
        # test_broken_sibling_does_not_sink_healthy_schema_sync.)
        manifest = _fanout_manifest()
        manifest["resources"].append(
            {
                "name": "broken",
                "primary_key": "id",
                "endpoint": {
                    "path": "/broken/{x}",
                    "params": {"x": {"type": "resolve", "resource": "nonexistent", "field": "id"}},
                },
            }
        )

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session")
    def test_fanout_runs_through_real_engine(self, mock_make_session):
        # End-to-end through the real REST engine (only the HTTP session is
        # mocked): the parent is fetched once, the child is requested per parent
        # row, and `include_from_parent` carries the parent id onto each child row.
        def _response(body: dict) -> Response:
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps(body).encode()
            resp.headers["Content-Type"] = "application/json"
            return resp

        session = mock_make_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = [
            _response({"items": [{"id": "f1"}, {"id": "f2"}]}),  # GET /forms
            _response({"items": [{"token": "r1"}, {"token": "r2"}]}),  # GET /forms/f1/responses
            _response({"items": [{"token": "r3"}]}),  # GET /forms/f2/responses
        ]

        manifest = _fanout_manifest()
        for resource in manifest["resources"]:
            resource["endpoint"]["paginator"] = {"type": "single_page"}
        manifest["resources"][1]["include_from_parent"] = ["id"]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        rows = [row for page in cast(Any, response.items()) for row in page]
        assert [row["token"] for row in rows] == ["r1", "r2", "r3"]
        # include_from_parent injects the parent id as `_<parent>_<field>`.
        assert [row["_forms_id"] for row in rows] == ["f1", "f1", "f2"]
        requested_paths = [call.args[0].url for call in session.prepare_request.call_args_list]
        assert requested_paths == [
            "https://api.example.com/forms",
            "https://api.example.com/forms/f1/responses",
            "https://api.example.com/forms/f2/responses",
        ]


class TestCustomSourceFanoutSchemasAndProbe(SimpleTestCase):
    def test_child_resource_is_its_own_schema(self):
        manifest = _fanout_manifest()
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schemas = {s.name: s for s in source.get_schemas(config, team_id=999)}

        assert set(schemas) == {"forms", "responses"}
        assert schemas["responses"].supports_incremental is True
        assert [f["field"] for f in schemas["responses"].incremental_fields] == ["submitted_at"]

    def test_broken_graph_does_not_break_schema_listing(self):
        # Schema listing runs on stored manifests; a graph error (which the
        # create-time validation now rejects, but older manifests may carry)
        # must not make it raise.
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schemas = {s.name for s in source.get_schemas(config, team_id=999)}
        assert schemas == {"forms", "responses"}

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_skips_fanout_child(self, mock_session):
        # The child can't be probed without a parent row, so only the parent is hit.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        probed_urls = [call.args[1] for call in mock_session.return_value.request.call_args_list]
        assert probed_urls == ["https://api.example.com/forms"]


class TestCustomSourceIncrementalDatetimeFormat(SimpleTestCase):
    def _manifest(self, datetime_format=None) -> dict:
        manifest = _minimal_manifest()
        incremental = {"cursor_path": "updated_at", "start_param": "since"}
        if datetime_format is not None:
            incremental["datetime_format"] = datetime_format
        manifest["resources"][0]["endpoint"]["incremental"] = incremental
        return manifest

    def _run(self, manifest, watermark):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=1,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        source.source_for_pipeline(config, inputs)

    _DT = datetime(2026, 6, 8, 12, 53, 34, tzinfo=UTC)

    @parameterized.expand(
        [
            ("typeform_z", "%Y-%m-%dT%H:%M:%SZ", _DT, "2026-06-08T12:53:34Z"),
            ("date_only", "%Y-%m-%d", _DT, "2026-06-08"),
            ("space_separated", "%Y-%m-%d %H:%M:%S", _DT, "2026-06-08 12:53:34"),
            ("iso8601_default", None, _DT, "2026-06-08T12:53:34+00:00"),
            ("string_passthrough", "%Y-%m-%dT%H:%M:%SZ", "2026-06-08T00:00:00Z", "2026-06-08T00:00:00Z"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_datetime_watermark_formatting(self, _name, fmt, watermark, expected, mock_resources):
        mock_resources.return_value = [_fake_resource("users")]
        self._run(self._manifest(fmt), watermark)

        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] == expected
        incremental = mock_resources.call_args.args[0]["resources"][0]["endpoint"]["incremental"]
        assert "datetime_format" not in incremental

    @parameterized.expand([("integer", 123), ("object", {"format": "%Y"}), ("list", ["%Y"])])
    def test_non_string_format_raises_non_retryable(self, _name, fmt):
        with self.assertRaises(NonRetryableException) as ctx:
            self._run(self._manifest(fmt), self._DT)
        assert "datetime_format" in str(ctx.exception)

    @parameterized.expand([("integer", 123), ("object", {"format": "%Y"})])
    def test_non_string_format_rejected_at_validation(self, _name, fmt):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(self._manifest(fmt)), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok is False
        assert err is not None and "datetime_format" in err and "'users'" in err

    @patch("posthog.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session")
    def test_datetime_format_reaches_request_through_real_engine(self, mock_make_session):
        def _response(body: dict) -> Response:
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps(body).encode()
            resp.headers["Content-Type"] = "application/json"
            return resp

        captured: list[dict] = []

        def send(prepared, **kwargs):
            captured.append(dict(getattr(prepared, "params", {}) or {}))
            if "/forms/f1/responses" in prepared.url:
                return _response({"items": []})
            return _response({"items": [{"id": "f1"}]})

        session = mock_make_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = send

        manifest = _fanout_manifest()
        for resource in manifest["resources"]:
            resource["endpoint"]["paginator"] = {"type": "single_page"}
        manifest["resources"][1]["endpoint"]["incremental"] = {
            "cursor_path": "submitted_at",
            "start_param": "since",
            "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=1,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 8, 12, 53, 34, tzinfo=UTC),
        )
        list(cast(Any, source.source_for_pipeline(config, inputs).items()))

        child_params = next((p for p in captured if "since" in p), {})
        assert child_params.get("since") == "2026-06-08T12:53:34Z"
