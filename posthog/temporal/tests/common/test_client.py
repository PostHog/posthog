import pytest

from parameterized import parameterized

from posthog.temporal.common.client import build_temporal_target


class TestBuildTemporalTarget:
    @parameterized.expand(
        [
            ("plain", "temporal", 7233, "temporal:7233"),
            ("string_port", "temporal", "7233", "temporal:7233"),
            ("strips_http_scheme", "http://temporal", 7233, "temporal:7233"),
            ("strips_grpc_scheme", "grpc://temporal", "7233", "temporal:7233"),
            ("strips_trailing_slash", "http://temporal/", 7233, "temporal:7233"),
            ("strips_surrounding_whitespace", "  temporal  ", " 7233 ", "temporal:7233"),
            ("ipv6_literal", "[::1]", 7233, "[::1]:7233"),
        ]
    )
    def test_builds_valid_target(self, _name: str, host: str, port: int | str, expected: str) -> None:
        assert build_temporal_target(host, port) == expected

    @parameterized.expand(
        [
            ("non_numeric_port", "temporal", "not-a-port", "TEMPORAL_PORT"),
            ("empty_port", "temporal", "", "TEMPORAL_PORT"),
            ("port_out_of_range", "temporal", "70000", "TEMPORAL_PORT"),
            ("zero_port", "temporal", 0, "TEMPORAL_PORT"),
            ("host_already_has_port", "temporal:7233", 7233, "TEMPORAL_HOST"),
            ("host_with_scheme_and_port", "http://temporal:7233", 7233, "TEMPORAL_HOST"),
            ("empty_host", "", 7233, "TEMPORAL_HOST"),
        ]
    )
    def test_rejects_malformed_target_naming_the_setting(
        self, _name: str, host: str, port: int | str, expected_setting: str
    ) -> None:
        with pytest.raises(ValueError, match=expected_setting):
            build_temporal_target(host, port)
