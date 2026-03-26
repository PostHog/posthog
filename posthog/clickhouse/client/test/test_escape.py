from typing import Any

import pytest

from parameterized import parameterized

from posthog.clickhouse.client.escape import substitute_params, substitute_params_for_display


class TestSubstituteParams:
    @parameterized.expand(
        [
            (
                "basic values",
                "SELECT * FROM table WHERE id = %(id)s AND name = %(name)s",
                {"id": 123, "name": "test"},
                ["123", "'test'"],
            ),
            (
                "sensitive values not redacted in execution mode",
                "SELECT * FROM s3(%(url)s, %(key)s, %(secret_sensitive)s)",
                {
                    "url": "s3://bucket/path",
                    "key": "AKIAIOSFODNN7EXAMPLE",
                    "secret_sensitive": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                },
                ["AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"],
            ),
        ]
    )
    def test_substitute_params(self, _name, query, params, expected_in_result):
        result = substitute_params(query, params)
        for expected in expected_in_result:
            assert expected in result

    def test_substitute_params_raises_error_for_non_dict(self):
        invalid_params: Any = [1, 2, 3]
        with pytest.raises(ValueError, match="Parameters are expected in dict form"):
            substitute_params("SELECT 1", invalid_params)


class TestSubstituteParamsForDisplay:
    @parameterized.expand(
        [
            (
                "basic values",
                "SELECT * FROM table WHERE id = %(id)s AND name = %(name)s",
                {"id": 123, "name": "test"},
                ["123", "'test'"],
                [],
                0,
            ),
            (
                "s3 parameters",
                "SELECT * FROM s3(%(url)s, %(access_key_sensitive)s, %(access_secret_sensitive)s)",
                {
                    "url": "s3://bucket/path",
                    "access_key_sensitive": "AKIAIOSFODNN7EXAMPLE",
                    "access_secret_sensitive": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                },
                ["s3://bucket/path", "[HIDDEN]"],
                ["AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"],
                2,
            ),
            (
                "azure blob parameters",
                "SELECT * FROM azureBlobStorage(%(storage_url)s, %(container)s, %(access_key_sensitive)s, %(access_secret_sensitive)s)",
                {
                    "storage_url": "https://account.blob.core.windows.net",
                    "container": "my-container",
                    "access_key_sensitive": "account-name",
                    "access_secret_sensitive": "super-secret-key",
                },
                ["https://account.blob.core.windows.net", "my-container", "[HIDDEN]"],
                ["account-name", "super-secret-key"],
                2,
            ),
            (
                "all parameters marked",
                "SELECT * FROM table WHERE key1 = %(key1_sensitive)s AND key2 = %(key2_sensitive)s",
                {"key1_sensitive": "secret1", "key2_sensitive": "secret2"},
                ["[HIDDEN]"],
                ["secret1", "secret2"],
                2,
            ),
            (
                "no marked parameters",
                "SELECT * FROM table WHERE id = %(id)s AND status = %(status)s",
                {"id": 42, "status": "active"},
                ["42", "'active'"],
                ["[HIDDEN]"],
                0,
            ),
        ]
    )
    def test_substitute_params_for_display(
        self, _name, query, params, expected_in_result, not_expected_in_result, hidden_count
    ):
        result = substitute_params_for_display(query, params)

        for expected in expected_in_result:
            assert expected in result, f"Expected '{expected}' in result"

        for not_expected in not_expected_in_result:
            assert not_expected not in result, f"Did not expect '{not_expected}' in result"

        assert result.count("[HIDDEN]") == hidden_count, f"Expected {hidden_count} [HIDDEN] occurrences"

    def test_substitute_params_for_display_raises_error_for_non_dict(self):
        invalid_params: Any = [1, 2, 3]
        with pytest.raises(ValueError, match="Parameters are expected in dict form"):
            substitute_params_for_display("SELECT 1", invalid_params)

    def test_substitute_params_for_display_empty_params(self):
        query = "SELECT * FROM table"
        params: dict[str, str] = {}
        result = substitute_params_for_display(query, params)
        assert result == query
