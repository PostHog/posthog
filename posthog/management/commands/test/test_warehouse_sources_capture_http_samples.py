import json
from io import StringIO

import pytest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from posthog.temporal.data_imports.sources.common.http.sampling import (
    CAPTURE_CONFIG_REDIS_KEY,
    CAPTURE_COUNTER_KEY_PREFIX,
    CaptureConfig,
)

COMMAND = "warehouse_sources_capture_http_samples"


@pytest.fixture
def fake_redis():
    """Minimal in-memory fake of the redis client surface the command uses."""
    store: dict[bytes, bytes] = {}
    ttls: dict[bytes, int] = {}

    client = MagicMock()

    def _set(key, value, ex=None):
        if isinstance(key, str):
            key = key.encode()
        if isinstance(value, str):
            value = value.encode()
        store[key] = value
        if ex is not None:
            ttls[key] = ex

    def _get(key):
        if isinstance(key, str):
            key = key.encode()
        return store.get(key)

    def _ttl(key):
        if isinstance(key, str):
            key = key.encode()
        return ttls.get(key, -1)

    def _delete(*keys):
        deleted = 0
        for k in keys:
            if isinstance(k, str):
                k = k.encode()
            if k in store:
                del store[k]
                ttls.pop(k, None)
                deleted += 1
        return deleted

    def _scan(cursor=0, match=None, count=200):
        # Single-pass scan emulation
        if match is None:
            keys = list(store.keys())
        else:
            # Convert glob to regex-ish — only support trailing *
            prefix = match.rstrip("*").encode() if isinstance(match, str) else match
            keys = [k for k in store.keys() if k.startswith(prefix)]
        return 0, keys

    client.set.side_effect = _set
    client.get.side_effect = _get
    client.ttl.side_effect = _ttl
    client.delete.side_effect = _delete
    client.scan.side_effect = _scan
    client._store = store

    with patch("posthog.management.commands.warehouse_sources_capture_http_samples.get_client", return_value=client):
        yield client


def _run(*args: str) -> str:
    out = StringIO()
    call_command(COMMAND, *args, stdout=out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


def test_enable_writes_redis_key_with_ttl(fake_redis):
    output = _run("enable", "--source-type", "stripe", "--limit", "10", "--ttl", "30m")

    raw = fake_redis._store.get(CAPTURE_CONFIG_REDIS_KEY.encode())
    assert raw is not None
    config = json.loads(raw)
    assert config["capture_id"]
    assert config["rules"][0]["source_type"] == "stripe"
    assert config["rules"][0]["limit"] == 10
    # TTL was passed through `ex` to set()
    assert fake_redis.set.call_args.kwargs["ex"] == 30 * 60
    assert "Capture enabled" in output
    assert "Rules:" in output


def test_enable_defaults_filters_to_wildcard(fake_redis):
    _run("enable")

    raw = fake_redis._store.get(CAPTURE_CONFIG_REDIS_KEY.encode())
    rule = json.loads(raw)["rules"][0]
    assert rule["source_type"] == "*"
    assert rule["response_code"] == "*"
    assert rule["team_id"] == "*"
    assert rule["schema_id"] == "*"


def test_enable_with_response_code_class(fake_redis):
    _run("enable", "--response-code", "4xx", "--limit", "5", "--ttl", "5m")

    raw = fake_redis._store.get(CAPTURE_CONFIG_REDIS_KEY.encode())
    rule = json.loads(raw)["rules"][0]
    assert rule["response_code"] == "4xx"


@pytest.mark.parametrize(
    "ttl_str,expected_seconds",
    [
        ("30s", 30),
        ("5m", 5 * 60),
        ("2h", 2 * 60 * 60),
        ("1d", 86400),
        ("600", 600),  # Plain integer fallback
    ],
)
def test_enable_parses_ttl_units(fake_redis, ttl_str, expected_seconds):
    _run("enable", "--ttl", ttl_str)
    assert fake_redis.set.call_args.kwargs["ex"] == expected_seconds


def test_enable_rejects_ttl_above_max(fake_redis):
    with pytest.raises(ValueError, match="exceeds max"):
        _run("enable", "--ttl", "48h")


def test_enable_rejects_invalid_ttl(fake_redis):
    with pytest.raises(ValueError, match="invalid ttl"):
        _run("enable", "--ttl", "not-a-duration")


def test_enable_supports_extra_rules(fake_redis):
    _run(
        "enable",
        "--source-type",
        "stripe",
        "--limit",
        "100",
        "--ttl",
        "30m",
        "--rule",
        "source_type=hubspot,response_code=*,team_id=12,limit=10",
        "--rule",
        "source_type=mailchimp,response_code=429,limit=5",
    )

    raw = fake_redis._store.get(CAPTURE_CONFIG_REDIS_KEY.encode())
    rules = json.loads(raw)["rules"]
    assert len(rules) == 3
    # Primary rule first
    assert rules[0]["source_type"] == "stripe" and rules[0]["limit"] == 100
    assert rules[1]["source_type"] == "hubspot" and rules[1]["team_id"] == "12"
    assert rules[2]["source_type"] == "mailchimp" and rules[2]["response_code"] == "429"


def test_enable_extra_rule_inherits_default_limit(fake_redis):
    """A --rule without limit should fall back to the --limit flag."""
    _run("enable", "--limit", "42", "--ttl", "30m", "--rule", "source_type=hubspot")

    raw = fake_redis._store.get(CAPTURE_CONFIG_REDIS_KEY.encode())
    rules = json.loads(raw)["rules"]
    assert rules[1]["limit"] == 42


def test_enable_rejects_malformed_rule(fake_redis):
    with pytest.raises(ValueError, match="invalid rule fragment"):
        _run("enable", "--ttl", "30m", "--rule", "no-equals-sign")


# ---------------------------------------------------------------------------
# disable
# ---------------------------------------------------------------------------


def test_disable_clears_key_and_counters(fake_redis):
    config = CaptureConfig(capture_id="cap-7", rules=())
    fake_redis._store[CAPTURE_CONFIG_REDIS_KEY.encode()] = config.to_json().encode()
    fake_redis._store[f"{CAPTURE_COUNTER_KEY_PREFIX}:cap-7:0".encode()] = b"3"
    fake_redis._store[f"{CAPTURE_COUNTER_KEY_PREFIX}:cap-7:seq:stripe".encode()] = b"5"

    output = _run("disable")

    assert CAPTURE_CONFIG_REDIS_KEY.encode() not in fake_redis._store
    assert f"{CAPTURE_COUNTER_KEY_PREFIX}:cap-7:0".encode() not in fake_redis._store
    assert f"{CAPTURE_COUNTER_KEY_PREFIX}:cap-7:seq:stripe".encode() not in fake_redis._store
    assert "Capture disabled" in output


def test_disable_when_already_disabled_is_noop(fake_redis):
    output = _run("disable")
    assert "already disabled" in output


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_when_disabled(fake_redis):
    output = _run("list")
    assert "not currently enabled" in output


def test_list_prints_active_config(fake_redis):
    _run("enable", "--source-type", "stripe", "--response-code", "4xx", "--limit", "20", "--ttl", "30m")
    output = _run("list")

    assert "capture_id:" in output
    assert "rules (1):" in output
    assert "source_type='stripe'" in output
    assert "response_code='4xx'" in output
    assert "limit=20" in output


def test_list_shows_per_rule_used_count(fake_redis):
    _run("enable", "--limit", "10", "--ttl", "30m")
    raw = fake_redis._store[CAPTURE_CONFIG_REDIS_KEY.encode()]
    cap_id = json.loads(raw)["capture_id"]
    fake_redis._store[f"{CAPTURE_COUNTER_KEY_PREFIX}:{cap_id}:0".encode()] = b"3"

    output = _run("list")
    assert "used=3/10" in output
