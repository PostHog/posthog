import json
import struct
import hashlib
from pathlib import Path

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

HASH_CORPUS = json.loads(
    (
        Path(__file__).resolve().parents[4]
        / "rust/feature-flags/tests/fixtures/rules_v2_contract/1.2.0/corpus/hash_sha1_60_v1.json"
    ).read_text()
)


class TestHashFunctions(BaseTest):
    @parameterized.expand(
        [
            ("empty", ""),
            ("ascii", "abc"),
            ("unicode", "ünïcødé-😀"),
            ("nul", "a\0b"),
            *[(f"length_{length}", "a" * length) for length in (55, 56, 63, 64, 65, 1000)],
        ]
    )
    def test_sha1_returns_binary_digest(self, _name: str, value: str):
        response = execute_hogql_query(
            "SELECT lower(hex(SHA1({value}))), length(SHA1({value})), toTypeName(SHA1({value}))",
            self.team,
            placeholders={"value": ast.Constant(value=value)},
        )

        assert response.results == [(hashlib.sha1(value.encode("utf-8")).hexdigest(), 20, "FixedString(20)")]

    def test_sha1_preserves_null(self):
        response = execute_hogql_query("SELECT SHA1(NULL)", self.team)

        assert response.results == [(None,)]

    @parameterized.expand([(vector["id"], vector) for vector in HASH_CORPUS["vectors"]])
    def test_sha1_matches_feature_flag_hash_contract(self, _name: str, vector: dict):
        response = execute_hogql_query(
            """
            SELECT
                lower(hex(digest)),
                hash_integer,
                hash_integer / 1152921504606846975
            FROM (
                SELECT
                    SHA1(concat({prefix}, {identifier}, {salt})) AS digest,
                    bitShiftRight(reinterpretAsUInt64(reverse(substring(digest, 1, 8))), 4) AS hash_integer
            )
            """,
            self.team,
            placeholders={key: ast.Constant(value=vector[key]) for key in ("prefix", "identifier", "salt")},
        )

        digest, hash_integer, bucket = response.results[0]
        assert digest == vector["sha1_hex"]
        assert hash_integer == int(vector["n"])
        assert struct.pack(">d", bucket).hex() == vector["hash01_binary64_hex"]
