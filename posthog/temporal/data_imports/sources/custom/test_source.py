import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from posthog.temporal.data_imports.sources.custom.source import (
    CustomSource,
    ManifestValidationError,
    validate_manifest,
    validate_manifest_urls,
)
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from posthog.temporal.data_imports.util import NonRetryableException

from products.data_warehouse.backend.types import IncrementalFieldType


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
    def test_rejects_absolute_resource_path_when_internal(self, mock_host_safe):
        manifest = _minimal_manifest()
        # https:// so the URL clears the scheme check and actually reaches the
        # host-safety check — an http:// path would be rejected on scheme alone.
        manifest["resources"][0]["endpoint"]["path"] = "https://127.0.0.1/leak"
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "users" in (err or "")
        # The internal host was actually run through _is_host_safe, not rejected
        # earlier on scheme alone.
        assert any(call.args[0] == "127.0.0.1" for call in mock_host_safe.call_args_list)


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
    def test_probes_every_resource(self, mock_session):
        # The second resource fails auth — validation must catch it, not stop at the first.
        manifest = _minimal_manifest()
        manifest["resources"].append({"name": "orders", "endpoint": {"path": "/orders"}})
        mock_session.return_value.request.side_effect = [
            MagicMock(status_code=200, text="{}"),
            MagicMock(status_code=403, text="forbidden"),
        ]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "orders" in (err or "")
        assert "403" in (err or "")

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

    def test_returns_false_on_invalid_manifest(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert err is not None

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_session_forwards_team_id(self, mock_session):
        # The probe forwards team_id to make_tracked_session — the hop that mounts
        # the SSRF guard (the guard itself is covered in test_http_transport).
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        source.validate_credentials(config, team_id=999)

        assert mock_session.call_args.kwargs["team_id"] == 999


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

    @parameterized.expand([("default_asc", None, "asc"), ("explicit_desc", "desc", "desc")])
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resource")
    def test_sort_mode_threaded_to_source_response(self, _name, declared, expected, _mock_resource):
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


class TestGetNonRetryableErrors(SimpleTestCase):
    def test_blocked_host_errors_are_non_retryable(self):
        # The keys must substring-match the BlockedHostError messages the SSRF
        # guard raises, the way import_data_sync._run classifies them.
        keys = CustomSource().get_non_retryable_errors().keys()
        assert any(key in "Blocked request to host '10.0.0.1': internal" for key in keys)
        assert any(key in "Blocked connection to 'host': peer '10.0.0.1' is an internal address" for key in keys)
