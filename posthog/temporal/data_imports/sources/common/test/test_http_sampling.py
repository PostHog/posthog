import json

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response

from posthog.temporal.data_imports.sources.common.http import sampling
from posthog.temporal.data_imports.sources.common.http.context import JobContext
from posthog.temporal.data_imports.sources.common.http.observer import RequestRecord
from posthog.temporal.data_imports.sources.common.http.sampling import (
    CAPTURE_CONFIG_REDIS_KEY,
    CaptureConfig,
    CaptureRule,
    _build_sample_payload,
    _scrub_body,
    _scrub_headers,
    maybe_capture,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    sampling._reset_cache_for_tests()
    yield
    sampling._reset_cache_for_tests()


def _make_ctx(team_id: int = 99, source_type: str = "stripe", schema_id: str = "schema-uuid") -> JobContext:
    return JobContext(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id="src-uuid",
        external_data_schema_id=schema_id,
        external_data_job_id="run-id",
    )


def _make_request(
    url: str = "https://api.stripe.com/v1/charges", method: str = "GET", body=None, headers=None
) -> PreparedRequest:
    req = PreparedRequest()
    req.prepare(method=method, url=url, data=body, headers=headers)
    return req


def _make_response(status: int = 200, body: bytes = b"", headers: dict | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = body
    if headers:
        resp.headers.update(headers)
    return resp


def _make_record(status_code: int = 200, latency_ms: int = 42) -> RequestRecord:
    return RequestRecord(
        method="GET",
        url="https://api.stripe.com/v1/charges",
        request_bytes=0,
        response_bytes=10,
        status_code=status_code,
        latency_ms=latency_ms,
        error_class=None,
    )


# ---------------------------------------------------------------------------
# CaptureRule.matches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule,source_type,status_code,team_id,schema_id,expected",
    [
        # All wildcards — always match
        (CaptureRule(), "stripe", 200, 99, "any", True),
        # source_type exact
        (CaptureRule(source_type="stripe"), "stripe", 200, 1, "x", True),
        (CaptureRule(source_type="stripe"), "hubspot", 200, 1, "x", False),
        # team_id exact (note: rule stores as str)
        (CaptureRule(team_id="99"), "stripe", 200, 99, "x", True),
        (CaptureRule(team_id="99"), "stripe", 200, 100, "x", False),
        # schema_id exact
        (CaptureRule(schema_id="abc"), "stripe", 200, 1, "abc", True),
        (CaptureRule(schema_id="abc"), "stripe", 200, 1, "def", False),
        # status_code exact
        (CaptureRule(response_code="200"), "stripe", 200, 1, "x", True),
        (CaptureRule(response_code="429"), "stripe", 200, 1, "x", False),
        # status_code class
        (CaptureRule(response_code="2xx"), "stripe", 204, 1, "x", True),
        (CaptureRule(response_code="2xx"), "stripe", 404, 1, "x", False),
        (CaptureRule(response_code="4xx"), "stripe", 429, 1, "x", True),
        (CaptureRule(response_code="5xx"), "stripe", 503, 1, "x", True),
        # status_code class with no status (e.g., network error) — never matches a class
        (CaptureRule(response_code="2xx"), "stripe", None, 1, "x", False),
        # status_code wildcard with None status — matches
        (CaptureRule(), "stripe", None, 1, "x", True),
        # Combined filters: all must match
        (
            CaptureRule(source_type="stripe", response_code="2xx", team_id="99", schema_id="abc"),
            "stripe",
            200,
            99,
            "abc",
            True,
        ),
        (
            CaptureRule(source_type="stripe", response_code="2xx", team_id="99", schema_id="abc"),
            "stripe",
            200,
            99,
            "def",
            False,
        ),
    ],
)
def test_capture_rule_matches(
    rule: CaptureRule,
    source_type: str,
    status_code: int | None,
    team_id: int,
    schema_id: str,
    expected: bool,
):
    assert (
        rule.matches(source_type=source_type, status_code=status_code, team_id=team_id, schema_id=schema_id) == expected
    )


def test_capture_rule_from_dict_uses_wildcard_for_missing_fields():
    rule = CaptureRule.from_dict({})
    assert rule.source_type == "*"
    assert rule.response_code == "*"
    assert rule.team_id == "*"
    assert rule.schema_id == "*"
    assert rule.limit == 0


def test_capture_rule_from_dict_coerces_types():
    rule = CaptureRule.from_dict({"team_id": 99, "limit": "50"})
    assert rule.team_id == "99"
    assert rule.limit == 50


# ---------------------------------------------------------------------------
# CaptureConfig.from_json
# ---------------------------------------------------------------------------


def test_capture_config_from_json_round_trip():
    raw = {
        "capture_id": "cap-123",
        "rules": [
            {"source_type": "stripe", "response_code": "2xx", "limit": 50},
            {"source_type": "hubspot", "limit": 10},
        ],
    }
    config = CaptureConfig.from_json(json.dumps(raw))

    assert config is not None
    assert config.capture_id == "cap-123"
    assert len(config.rules) == 2
    assert config.rules[0].source_type == "stripe"
    assert config.rules[0].limit == 50
    assert config.rules[1].source_type == "hubspot"


def test_capture_config_from_json_rejects_missing_capture_id():
    config = CaptureConfig.from_json(json.dumps({"rules": []}))
    assert config is None


def test_capture_config_from_json_ignores_non_dict_rules():
    raw = {"capture_id": "x", "rules": [{"source_type": "stripe"}, "not-a-dict", 123]}
    config = CaptureConfig.from_json(json.dumps(raw))

    assert config is not None
    assert len(config.rules) == 1


def test_capture_config_from_json_returns_none_on_invalid_json():
    assert CaptureConfig.from_json("not-json") is None
    assert CaptureConfig.from_json(b"\x00\xff") is None


def test_capture_config_to_json_round_trips():
    config = CaptureConfig(
        capture_id="cap",
        rules=(CaptureRule(source_type="stripe", limit=10),),
    )
    rebuilt = CaptureConfig.from_json(config.to_json())

    assert rebuilt is not None
    assert rebuilt.capture_id == "cap"
    assert rebuilt.rules[0].source_type == "stripe"
    assert rebuilt.rules[0].limit == 10


# ---------------------------------------------------------------------------
# In-process config cache TTL
# ---------------------------------------------------------------------------


def test_load_config_caches_within_ttl():
    """Two consecutive loads within TTL should hit Redis exactly once."""
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"capture_id": "x", "rules": []}).encode()

    monotonic = [1000.0]
    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling._now", side_effect=lambda: monotonic[0]),
    ):
        first = sampling._load_config()
        second = sampling._load_config()

    assert first is not None
    assert second is first
    assert fake_redis.get.call_count == 1


def test_load_config_refreshes_after_ttl():
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"capture_id": "x", "rules": []}).encode()

    monotonic = [1000.0]
    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling._now", side_effect=lambda: monotonic[0]),
    ):
        sampling._load_config()
        monotonic[0] += sampling.CONFIG_CACHE_TTL_SECONDS + 1
        sampling._load_config()

    assert fake_redis.get.call_count == 2


def test_load_config_returns_cached_on_redis_error():
    fake_redis = MagicMock()
    # First call succeeds, second raises
    fake_redis.get.side_effect = [
        json.dumps({"capture_id": "x", "rules": []}).encode(),
        RuntimeError("redis down"),
    ]

    monotonic = [1000.0]
    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling._now", side_effect=lambda: monotonic[0]),
    ):
        first = sampling._load_config()
        # Force cache expiry, second call hits Redis but Redis raises
        monotonic[0] += sampling.CONFIG_CACHE_TTL_SECONDS + 1
        second = sampling._load_config()

    assert first is not None
    assert second is first  # Falls back to last-known-good


def test_load_config_returns_none_when_key_absent():
    fake_redis = MagicMock()
    fake_redis.get.return_value = None

    with patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis):
        assert sampling._load_config() is None


# ---------------------------------------------------------------------------
# Slot reservation (Redis INCR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "limit,sequence,expected_results",
    [
        # limit=0 → no slots ever
        (0, [1], [False]),
        # limit=3 → first 3 reserved, rest rejected
        (3, [1, 2, 3, 4, 5], [True, True, True, False, False]),
    ],
)
def test_try_reserve_slot_enforces_limit(limit: int, sequence: list[int], expected_results: list[bool]):
    fake_redis = MagicMock()
    fake_redis.incr.side_effect = sequence
    fake_redis.ttl.return_value = 600

    with patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis):
        results = [sampling._try_reserve_slot("cap", 0, limit) for _ in sequence]

    assert results == expected_results


def test_try_reserve_slot_returns_false_on_redis_error():
    fake_redis = MagicMock()
    fake_redis.incr.side_effect = RuntimeError("redis down")

    with patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis):
        assert sampling._try_reserve_slot("cap", 0, 10) is False


# ---------------------------------------------------------------------------
# Sample payload shape and S3 layout
# ---------------------------------------------------------------------------


def test_sample_object_key_format():
    key = sampling._sample_object_key("cap-123", "stripe", 7)
    assert key == "warehouse-sources-http-samples/cap-123/stripe/000007.json"


def test_sample_payload_contains_request_and_response():
    request = _make_request(
        url="https://api.stripe.com/v1/charges",
        method="POST",
        body=b'{"amount": 1000}',
    )
    response = _make_response(status=200, body=b'{"id": "ch_1"}', headers={"Content-Type": "application/json"})

    payload = _build_sample_payload(
        request=request,
        response=response,
        record=_make_record(),
        ctx=_make_ctx(),
    )
    parsed = json.loads(payload)

    assert "request" in parsed
    assert "response" in parsed
    assert parsed["request"]["method"] == "POST"
    assert parsed["request"]["url"].startswith("https://api.stripe.com/")
    assert parsed["response"]["status"] == 200
    assert parsed["response"]["elapsed_ms"] == 42
    assert parsed["context"]["team_id"] == 99
    assert parsed["context"]["source_type"] == "stripe"
    assert "captured_at_unix_ms" in parsed


def test_sample_payload_redacts_url_query_params():
    request = _make_request(url="https://api.stripe.com/v1/charges?api_key=secret&page=2")
    response = _make_response(status=200, body=b"{}")

    payload = _build_sample_payload(
        request=request,
        response=response,
        record=_make_record(),
        ctx=_make_ctx(),
    )
    parsed = json.loads(payload)

    assert "secret" not in parsed["request"]["url"]
    assert "REDACTED" in parsed["request"]["url"]


def test_sample_payload_preserves_json_body_keys():
    """User explicit ask: don't drop keys, only anonymize values."""
    request = _make_request(
        url="https://api.stripe.com/v1/customers",
        method="POST",
        body=b'{"email": "alice@example.com", "name": "Alice", "id": 42}',
        headers={"Content-Type": "application/json"},
    )
    response = _make_response(
        status=200,
        body=b'{"customer_id": "cus_x", "email": "alice@example.com"}',
        headers={"Content-Type": "application/json"},
    )

    payload = _build_sample_payload(
        request=request,
        response=response,
        record=_make_record(),
        ctx=_make_ctx(),
    )
    parsed = json.loads(payload)

    # All keys must survive, even if values get scrubbed.
    assert set(parsed["request"]["body"].keys()) == {"email", "name", "id"}
    assert set(parsed["response"]["body"].keys()) == {"customer_id", "email"}
    # Email values should be scrubbed (replaced with a placeholder by scrubadub).
    assert parsed["request"]["body"]["email"] != "alice@example.com"
    assert parsed["response"]["body"]["email"] != "alice@example.com"
    # The non-PII id field passes through unchanged.
    assert parsed["request"]["body"]["id"] == 42


# ---------------------------------------------------------------------------
# Header scrubbing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header_name",
    ["Authorization", "authorization", "X-API-Key", "x-auth-token", "Cookie", "Set-Cookie", "Proxy-Authorization"],
)
def test_scrub_headers_redacts_auth_headers(header_name: str):
    cleaned = _scrub_headers({header_name: "Bearer sk_live_secret"})
    assert cleaned[header_name] == "REDACTED"


def test_scrub_headers_passes_through_innocuous_headers():
    cleaned = _scrub_headers({"Content-Type": "application/json", "Accept": "*/*"})
    assert cleaned["Content-Type"] == "application/json"
    assert cleaned["Accept"] == "*/*"


# ---------------------------------------------------------------------------
# Body scrubbing
# ---------------------------------------------------------------------------


def test_scrub_body_handles_json_dict():
    out = _scrub_body('{"email": "alice@example.com", "ok": true}')
    assert isinstance(out, dict)
    assert set(out.keys()) == {"email", "ok"}
    assert out["email"] != "alice@example.com"
    assert out["ok"] is True


def test_scrub_body_handles_json_list():
    out = _scrub_body('[{"email": "a@b.com"}, "free text"]')
    assert isinstance(out, list)
    assert len(out) == 2
    assert "email" in out[0]


def test_scrub_body_passes_through_non_json_string():
    out = _scrub_body("just a string")
    assert isinstance(out, str)


def test_scrub_body_decodes_bytes():
    out = _scrub_body(b'{"x": 1}')
    assert isinstance(out, dict)
    assert out["x"] == 1


def test_scrub_body_falls_back_for_binary():
    # Raw binary that won't decode as utf-8
    out = _scrub_body(b"\x00\xff\xfe")
    assert isinstance(out, str)
    assert "binary" in out


def test_scrub_body_handles_none():
    assert _scrub_body(None) is None


def test_scrub_string_fails_closed_when_scrubadub_fails():
    """A scrubadub crash must NOT leak the raw value — replace with a placeholder."""
    with patch(
        "posthog.temporal.data_imports.sources.common.http.sampling._get_scrubber",
        side_effect=RuntimeError("scrubadub broken"),
    ):
        result = sampling._scrub_string("super-secret-token-123")
    assert result == "<scrub_failed>"
    assert "super-secret-token-123" not in result


# ---------------------------------------------------------------------------
# OAuth / form-urlencoded body scrubbing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,redacted_keys",
    [
        # HubSpot-style refresh
        (
            "grant_type=refresh_token&client_id=cid&client_secret=cs&refresh_token=rt",
            {"client_secret", "refresh_token"},
        ),
        # Salesforce / generic OAuth code exchange
        (
            "grant_type=authorization_code&client_id=cid&client_secret=cs&redirect_uri=https://x/y&code=abc",
            {"client_secret", "code"},
        ),
        # Token exchange (RFC 8693)
        (
            "grant_type=urn:ietf:params:oauth:grant-type:token-exchange"
            "&subject_token=st&actor_token=at&client_assertion=ca&client_assertion_type=cat",
            {"subject_token", "actor_token", "client_assertion", "client_assertion_type"},
        ),
        # Bearer token in arbitrary form param
        ("api_key=secret&page=2", {"api_key"}),
    ],
)
def test_scrub_body_redacts_oauth_form_secrets(body: str, redacted_keys: set[str]):
    """`_scrub_body` must NEVER pass OAuth form payloads to scrubadub raw."""
    out = _scrub_body(body)
    assert isinstance(out, str)
    assert "REDACTED" in out
    # Non-redacted keys are still present (we preserve form structure).
    parsed_pairs = dict(p.split("=", 1) for p in out.split("&"))
    for key in redacted_keys:
        assert parsed_pairs.get(key) == "REDACTED", f"{key} should be redacted, got {parsed_pairs.get(key)}"


def test_scrub_body_form_preserves_non_redacted_values():
    """Non-secret form params like `grant_type` flow through, keys remain, secrets get REDACTED."""
    out = _scrub_body("grant_type=refresh_token&page=2&client_secret=secret")
    assert isinstance(out, str)
    parsed = dict(p.split("=", 1) for p in out.split("&"))
    assert parsed["grant_type"] == "refresh_token"
    assert parsed["page"] == "2"
    assert parsed["client_secret"] == "REDACTED"


def test_scrub_body_does_not_treat_freeform_text_as_form():
    """Plain text without `key=value` shape still falls back to scrubadub."""
    out = _scrub_body("this is just a sentence with no equals signs")
    assert isinstance(out, str)


def test_scrub_body_does_not_treat_short_kv_with_spaces_as_form():
    """A single 'foo = bar' phrase isn't form-encoded — must not redact."""
    out = _scrub_body("foo bar = baz")
    # We don't try to redact key-shaped substrings here.
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# maybe_capture end-to-end
# ---------------------------------------------------------------------------


def test_maybe_capture_no_op_when_no_config():
    fake_redis = MagicMock()
    fake_redis.get.return_value = None

    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling.object_storage.write") as write,
    ):
        maybe_capture(
            request=_make_request(),
            response=_make_response(),
            record=_make_record(),
            ctx=_make_ctx(),
        )

    write.assert_not_called()


def test_maybe_capture_writes_to_s3_when_rule_matches():
    config = {
        "capture_id": "cap-7",
        "rules": [{"source_type": "stripe", "response_code": "2xx", "limit": 5}],
    }
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps(config).encode()
    fake_redis.incr.return_value = 1
    fake_redis.ttl.return_value = 600

    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling.object_storage.write") as write,
    ):
        maybe_capture(
            request=_make_request(url="https://api.stripe.com/v1/charges"),
            response=_make_response(status=200, body=b'{"id": "ch_x"}'),
            record=_make_record(status_code=200),
            ctx=_make_ctx(),
        )

    write.assert_called_once()
    key = write.call_args.args[0]
    assert key.startswith("warehouse-sources-http-samples/cap-7/stripe/")
    assert key.endswith(".json")


def test_maybe_capture_no_op_when_no_rule_matches():
    config = {
        "capture_id": "cap-7",
        "rules": [{"source_type": "hubspot", "limit": 5}],  # different source
    }
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps(config).encode()

    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling.object_storage.write") as write,
    ):
        maybe_capture(
            request=_make_request(),
            response=_make_response(status=200),
            record=_make_record(),
            ctx=_make_ctx(source_type="stripe"),
        )

    write.assert_not_called()


def test_maybe_capture_no_op_when_response_is_none():
    """Without a response, we have nothing to capture."""
    config = {"capture_id": "cap", "rules": [{"limit": 5}]}
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps(config).encode()

    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling.object_storage.write") as write,
    ):
        maybe_capture(
            request=_make_request(),
            response=None,
            record=_make_record(),
            ctx=_make_ctx(),
        )

    write.assert_not_called()


def test_maybe_capture_first_match_wins():
    """When multiple rules match, only the first is used (and only one slot reserved)."""
    config = {
        "capture_id": "cap",
        "rules": [
            {"source_type": "stripe", "limit": 5},
            {"source_type": "*", "limit": 10},
        ],
    }
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps(config).encode()
    fake_redis.incr.return_value = 1
    fake_redis.ttl.return_value = 600

    with (
        patch("posthog.temporal.data_imports.sources.common.http.sampling.get_client", return_value=fake_redis),
        patch("posthog.temporal.data_imports.sources.common.http.sampling.object_storage.write"),
    ):
        maybe_capture(
            request=_make_request(),
            response=_make_response(status=200),
            record=_make_record(),
            ctx=_make_ctx(),
        )

    # First INCR is for the rule_index=0 counter; second for the per-source sequence.
    counter_keys = [c.args[0] for c in fake_redis.incr.call_args_list]
    assert any(":0" in k and "seq" not in k for k in counter_keys)
    assert not any(":1" in k for k in counter_keys)  # second rule never incremented


def test_redis_capture_config_key_constant_is_stable():
    """Bumping the key would silently drop active capture sessions — make this explicit."""
    assert CAPTURE_CONFIG_REDIS_KEY == "data_imports:http_sample_capture"
