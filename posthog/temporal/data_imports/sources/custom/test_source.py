import json

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.data_imports.sources.custom.manifest_validators import (
    ManifestValidationError,
    redact_manifest_secrets,
    validate_manifest,
    validate_manifest_urls,
)
from posthog.temporal.data_imports.sources.custom.source import CustomSource
from posthog.temporal.data_imports.sources.generated_configs import CustomSourceConfig


def _minimal_manifest(base_url: str = "https://api.example.com") -> dict:
    return {
        "client": {
            "base_url": base_url,
            "auth": {"type": "bearer", "token": "abc"},
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
            ({}, "missing required keys"),
            (
                {"client": {"base_url": "https://x"}, "resources": []},
                "must be a non-empty list",
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

    def test_rejects_unknown_http_method(self):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["method"] = "TRACE"
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "method" in str(ctx.exception)


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
        "posthog.temporal.data_imports.sources.custom.manifest_validators.is_http_host_safe",
        side_effect=lambda host, team_id: (host != "127.0.0.1", None if host != "127.0.0.1" else "blocked"),
    )
    def test_rejects_absolute_resource_path_when_internal(self, _mock):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["path"] = "http://127.0.0.1/leak"
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "users" in (err or "")


class TestCustomSourceParseManifest(SimpleTestCase):
    def test_parse_manifest_rejects_invalid_json(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        with self.assertRaises(ManifestValidationError):
            source._parse_manifest(config)

    def test_parse_manifest_returns_dict(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        manifest = source._parse_manifest(config)
        assert manifest["client"]["base_url"] == "https://api.example.com"


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


class TestCustomSourceValidateCredentials(SimpleTestCase):
    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_true_on_2xx(self, mock_session):
        response = MagicMock(status_code=200, text="{}")
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert err is None

    @patch("posthog.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_false_on_4xx(self, mock_session):
        response = MagicMock(status_code=401, text="unauthorized")
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "401" in (err or "")


class TestRedactManifestSecrets(SimpleTestCase):
    @parameterized.expand(
        [
            ("bearer", {"type": "bearer", "token": "secret"}, {"type": "bearer", "token": ""}),
            (
                "api_key",
                {"type": "api_key", "api_key": "sk_test", "name": "Authorization", "location": "header"},
                {"type": "api_key", "api_key": "", "name": "Authorization", "location": "header"},
            ),
            (
                "http_basic",
                {"type": "http_basic", "username": "alice", "password": "hunter2"},
                {"type": "http_basic", "username": "alice", "password": ""},
            ),
        ]
    )
    def test_blanks_only_credential_leaves(self, _name, auth, expected_auth):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth
        redacted = redact_manifest_secrets(manifest)
        assert redacted["client"]["auth"] == expected_auth
        # Non-credential fields are preserved verbatim.
        assert redacted["client"]["base_url"] == manifest["client"]["base_url"]
        assert redacted["resources"] == manifest["resources"]

    def test_is_a_no_op_when_no_auth_block(self):
        manifest = {"client": {"base_url": "https://x"}, "resources": [{"name": "r", "endpoint": {"path": "/r"}}]}
        assert redact_manifest_secrets(manifest) == manifest

    def test_does_not_mutate_input(self):
        manifest = _minimal_manifest()
        original_token = manifest["client"]["auth"]["token"]
        redact_manifest_secrets(manifest)
        assert manifest["client"]["auth"]["token"] == original_token
