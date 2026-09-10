import hmac
import hashlib

import pytest

from parameterized import parameterized

from common.hogvm.python.stl import STL
from common.hogvm.python.stl.crypto import sha1, sha1HmacChain

# RFC 2202 HMAC-SHA1 test vectors, limited to the cases whose key and message are text (the STL
# only takes strings). A two-element chain is a plain HMAC of key and message.
RFC_2202_VECTORS = [
    ("case_1", "\x0b" * 20, "Hi There", "b617318655057264e28bc0b6fb378c8ef146be00"),
    ("case_2", "Jefe", "what do ya want for nothing?", "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79"),
    ("case_5", "\x0c" * 20, "Test With Truncation", "4c1a03424b55e07fe7f27be1d58bb9324a9a5a04"),
]


class TestSha1:
    @parameterized.expand(
        [
            ("empty", "", "hex", "da39a3ee5e6b4b0d3255bfef95601890afd80709"),
            ("abc", "abc", "hex", "a9993e364706816aba3e25717850c26c9cd0d89d"),
            ("hello", "hello", "hex", "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"),
            ("base64", "abc", "base64", "qZk+NkcGgWq6PiVxeFDCbJzQ2J0="),
            ("base64url", "abc", "base64url", "qZk-NkcGgWq6PiVxeFDCbJzQ2J0"),
        ]
    )
    def test_known_answers(self, _name: str, data: str, encoding: str, expected: str) -> None:
        assert sha1(data, encoding) == expected  # type: ignore[arg-type]

    def test_defaults_to_hex(self) -> None:
        assert sha1("abc") == sha1("abc", "hex")

    def test_null_passes_through(self) -> None:
        assert sha1(None) is None

    def test_binary_encoding_holds_the_raw_digest(self) -> None:
        binary = sha1("abc", "binary")
        assert binary is not None
        assert binary.encode("latin1").hex() == sha1("abc", "hex")


class TestSha1HmacChain:
    @parameterized.expand(RFC_2202_VECTORS)
    def test_rfc_2202(self, _name: str, key: str, message: str, expected: str) -> None:
        assert sha1HmacChain([key, message]) == expected

    def test_rekeys_with_the_previous_raw_digest(self) -> None:
        # SHA-1 here is the algorithm under test, computed independently of the STL to pin the
        # re-keying step. Not used for secrecy or collision resistance.
        # nosemgrep: python.lang.security.insecure-hash-algorithms-sha1.insecure-hash-algorithm-sha1
        key = hmac.new(b"1", b"string", hashlib.sha1).digest()
        # nosemgrep: python.lang.security.insecure-hash-algorithms-sha1.insecure-hash-algorithm-sha1
        expected = hmac.new(key, b"more", hashlib.sha1).hexdigest()
        assert sha1HmacChain(["1", "string", "more"]) == expected

    @parameterized.expand(
        [
            ("hex", "hex", "e559ff0c3fc9c9e13a5b5d78fcd722b4f7ec6a9a"),
            ("base64", "base64", "5Vn/DD/JyeE6W114/NcitPfsapo="),
            ("base64url", "base64url", "5Vn_DD_JyeE6W114_NcitPfsapo"),
        ]
    )
    def test_encodings(self, _name: str, encoding: str, expected: str) -> None:
        assert sha1HmacChain(["1", "string", "more", "keys"], encoding) == expected  # type: ignore[arg-type]

    def test_rejects_short_input(self) -> None:
        with pytest.raises(ValueError):
            sha1HmacChain(["only-a-key"])


class TestStlRegistration:
    @parameterized.expand(
        [
            ("sha1Hex", ["abc"], "a9993e364706816aba3e25717850c26c9cd0d89d"),
            ("sha1", ["abc"], "a9993e364706816aba3e25717850c26c9cd0d89d"),
            ("sha1", ["abc", "base64"], "qZk+NkcGgWq6PiVxeFDCbJzQ2J0="),
            (
                "sha1HmacChainHex",
                [["Jefe", "what do ya want for nothing?"]],
                "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79",
            ),
            (
                "sha1HmacChain",
                [["Jefe", "what do ya want for nothing?"], "hex"],
                "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79",
            ),
        ]
    )
    def test_callable_through_stl(self, name: str, args: list, expected: str) -> None:
        assert STL[name].fn(args, None, None, 10.0) == expected
