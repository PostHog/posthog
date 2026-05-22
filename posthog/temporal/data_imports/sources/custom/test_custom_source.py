import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth, BearerTokenAuth, HttpBasicAuth
from posthog.temporal.data_imports.sources.custom.source import (
    CustomSource,
    ManifestValidationError,
    is_custom_source_available_for_team,
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

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_session_forwards_team_id(self, mock_session):
        # The probe forwards team_id to make_tracked_session — the hop that mounts
        # the SSRF guard (the guard itself is covered in test_http_transport).
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        source.validate_credentials(config, team_id=999)

        assert mock_session.call_args.kwargs["team_id"] == 999


class TestIsCustomSourceAvailableForTeam(SimpleTestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_allows_pilot_team_on_us_cloud(self):
        assert is_custom_source_available_for_team(2) is True

    @parameterized.expand([("EU",), ("DEV",), ("E2E",), ("",), (None,)])
    def test_rejects_non_us_deployment(self, deployment):
        with override_settings(CLOUD_DEPLOYMENT=deployment):
            assert is_custom_source_available_for_team(2) is False

    @parameterized.expand([(1,), (3,), (999,), (None,)])
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_rejects_other_teams_even_on_us(self, team_id):
        assert is_custom_source_available_for_team(team_id) is False


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

    @parameterized.expand(
        [
            ("opted_in", True, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            ("opted_out_drops_value", False, "2024-01-01T00:00:00Z", None),
            ("opted_in_none", True, None, None),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resource")
    def test_incremental_last_value_threaded_to_rest_engine(
        self, _name, should_use_incremental, last_value, expected, mock_resource
    ):
        # The high-watermark must only reach the REST engine when the schema is
        # configured for incremental sync — otherwise a full refresh would skip rows.
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

        assert mock_resource.call_args.kwargs["db_incremental_field_last_value"] == expected

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
    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resource")
    def test_paginator_config_threaded_to_rest_engine(self, _name, paginator_config, mock_resource):
        # Every PaginatorType the REST engine knows about must round-trip through
        # the custom source — paginator config is passed through untouched and the
        # REST engine selects the paginator at sync time.
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

        threaded_config = mock_resource.call_args.args[0]
        assert threaded_config["client"]["paginator"] == paginator_config

    @patch("posthog.temporal.data_imports.sources.custom.source.rest_api_resource")
    def test_cursor_type_stripped_before_rest_engine(self, mock_resource):
        # cursor_type informs schema field typing but is not a valid kwarg for the
        # engine's Incremental(**config) — it must be removed before the manifest
        # reaches rest_api_resource, while the other incremental keys survive.
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

        threaded_incremental = mock_resource.call_args.args[0]["resources"][0]["endpoint"]["incremental"]
        assert threaded_incremental == {"cursor_path": "updated_at", "start_param": "since"}


class TestGetNonRetryableErrors(SimpleTestCase):
    def test_blocked_host_errors_are_non_retryable(self):
        # The keys must substring-match the BlockedHostError messages the SSRF
        # guard raises, the way import_data_sync._run classifies them.
        keys = CustomSource().get_non_retryable_errors().keys()
        assert any(key in "Blocked request to host '10.0.0.1': internal" for key in keys)
        assert any(key in "Blocked connection to 'host': peer '10.0.0.1' is an internal address" for key in keys)
