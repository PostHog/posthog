import hmac
import json
import base64
import struct
import hashlib
from pathlib import Path
from typing import Any

import pytest

from posthog.integrations.mirror.canonical import DigestParts, canonical_json, content_digest

# The credentials service tests read the same file, so a vector added there pins both sides.
VECTORS_PATH = (
    Path(__file__).resolve().parents[4]
    / "services"
    / "credentials-service"
    / "tests"
    / "fixtures"
    / "content-digest-vectors.json"
)
VECTORS: list[dict[str, Any]] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
VALUE_VECTORS = [vector for vector in VECTORS if "parts" not in vector]
PARTS_VECTORS = [vector for vector in VECTORS if "parts" in vector]

PARTS = DigestParts(config={"a": 1}, errors="", external_id="x", sensitive_config={"token": "t"}, unreadable_keys=[])


def _hmac_hex(salt: bytes, message: str) -> str:
    return hmac.new(salt, message.encode("utf-8"), hashlib.sha256).hexdigest()


def _replace(**changes: Any) -> DigestParts:
    fields = {
        "config": PARTS.config,
        "errors": PARTS.errors,
        "external_id": PARTS.external_id,
        "sensitive_config": PARTS.sensitive_config,
        "unreadable_keys": PARTS.unreadable_keys,
    }
    return DigestParts(**{**fields, **changes})


def test_fixture_has_value_and_parts_vectors() -> None:
    assert VALUE_VECTORS
    assert PARTS_VECTORS


@pytest.mark.parametrize("vector", VALUE_VECTORS, ids=[vector["name"] for vector in VALUE_VECTORS])
def test_canonical_json_matches_vector(vector: dict[str, Any]) -> None:
    canonical = canonical_json(vector["value"])

    assert canonical == vector["canonical"]
    assert _hmac_hex(base64.b64decode(vector["salt_b64"]), canonical) == vector["digest"]
    if "ieee_hex" in vector and vector["ieee_hex"] != "8000000000000000":
        # json.loads reads "-0" as the int 0, so the minus-zero vector cannot round-trip its sign bit.
        assert struct.pack(">d", float(vector["value"])).hex() == vector["ieee_hex"]


@pytest.mark.parametrize("vector", PARTS_VECTORS, ids=[vector["name"] for vector in PARTS_VECTORS])
def test_content_digest_matches_vector(vector: dict[str, Any]) -> None:
    salt = base64.b64decode(vector["salt_b64"])

    digest = content_digest(salt, DigestParts(**vector["parts"]))

    assert digest == vector["digest"]
    assert _hmac_hex(salt, vector["canonical"]) == digest


@pytest.mark.parametrize(
    "value,expected",
    [
        (-0.0, "0"),
        (2**53, "9007199254740992"),
        (-(2**68), "-295147905179352830000"),
        (10**21, "1e+21"),
        (1e-6, "0.000001"),
        (1e-7, "1e-7"),
        (123e-20, "1.23e-18"),
        (0.1 + 0.2, "0.30000000000000004"),
        (True, "true"),
        (False, "false"),
        ({"b": 1, "a": None}, '{"a":null,"b":1}'),
        # Two code points that form a surrogate pair are one character to JavaScript.
        ("\ud83d\ude00", '"\U0001f600"'),
        ({"\ud83d\ude00": 1}, '{"\U0001f600":1}'),
        ("\x7f /", '"\x7f /"'),
    ],
)
def test_canonical_json_python_only_inputs(value: Any, expected: str) -> None:
    assert canonical_json(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        10**400,
        2**53 + 1,
        -(2**53 + 1),
        10**21 + 1,
        json.loads('{"account_id": 9007199254740993}'),
        (1, 2),
        {1, 2},
        b"bytes",
        {1: "non-string key"},
        {"nested": [float("nan")]},
        {"\U0001f600": 1, "\ud83d\ude00": 2},
        object(),
    ],
    ids=[
        "nan",
        "inf",
        "-inf",
        "int-out-of-double-range",
        "2^53+1",
        "-(2^53+1)",
        "10^21+1",
        "inexact-int-in-object",
        "tuple",
        "set",
        "bytes",
        "non-string-key",
        "nested-nan",
        "keys-equal-in-utf16",
        "object",
    ],
)
def test_canonical_json_rejects(value: Any) -> None:
    with pytest.raises(ValueError):
        canonical_json(value)


def test_digest_parts_repr_hides_sensitive_config() -> None:
    parts = _replace(sensitive_config={"access_token": "fake-secret-value"})

    assert "fake-secret-value" not in repr(parts)
    assert "sensitive_config" not in repr(parts)


def test_content_digest_changes_with_salt() -> None:
    a = content_digest(b"salt-a", PARTS)
    b = content_digest(b"salt-b", PARTS)

    assert len(a) == 64 and a == a.lower()
    assert a != b


def test_content_digest_ignores_unreadable_keys_order() -> None:
    assert content_digest(b"salt-a", _replace(unreadable_keys=["b", "a"])) == content_digest(
        b"salt-a", _replace(unreadable_keys=["a", "b"])
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"config": {"a": 2}},
        {"errors": "failed"},
        {"external_id": None},
        {"sensitive_config": {"token": "u"}},
        {"unreadable_keys": ["token"]},
    ],
    ids=["config", "errors", "external_id", "sensitive_config", "unreadable_keys"],
)
def test_content_digest_changes_with_each_part(changes: dict[str, Any]) -> None:
    assert content_digest(b"salt-a", _replace(**changes)) != content_digest(b"salt-a", PARTS)


@pytest.mark.parametrize(
    "salt,parts",
    [
        (b"", PARTS),
        ("salt-a", PARTS),
        (b"salt-a", _replace(config=["not", "an", "object"])),
        (b"salt-a", _replace(errors=None)),
        (b"salt-a", _replace(external_id=1)),
        (b"salt-a", _replace(unreadable_keys="ab")),
        (b"salt-a", _replace(unreadable_keys=[1])),
        (b"salt-a", _replace(unreadable_keys=None)),
        (b"salt-a", _replace(unreadable_keys=(key for key in ["a", "b"]))),
        (b"salt-a", _replace(unreadable_keys={"a", "b"})),
        (b"salt-a", _replace(unreadable_keys={"a": 1})),
        (b"salt-a", _replace(config={"account_id": 2**53 + 1})),
    ],
    ids=[
        "empty-salt",
        "str-salt",
        "config-not-object",
        "errors-not-string",
        "external-id-not-string",
        "unreadable-keys-string",
        "unreadable-keys-not-strings",
        "unreadable-keys-none",
        "unreadable-keys-generator",
        "unreadable-keys-set",
        "unreadable-keys-dict",
        "config-inexact-int",
    ],
)
def test_content_digest_rejects(salt: Any, parts: DigestParts) -> None:
    with pytest.raises(ValueError):
        content_digest(salt, parts)
