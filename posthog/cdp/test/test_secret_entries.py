from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.cdp.secret_entries import (
    merge_secret_entries,
    missing_secret_entries,
    recover_secret_entries,
    secret_entry_names,
    split_secret_entries,
)


class TestSecretEntries(SimpleTestCase):
    def _headers_input(self) -> dict:
        return {
            "value": {"Content-Type": "application/json", "x-api-token": "tok_HqZ2NmVrTt"},
            "bytecode": {
                "Content-Type": ["_H", 1, 32, "application/json"],
                "x-api-token": ["_H", 1, 32, "tok_HqZ2NmVrTt"],
            },
            "secret_keys": ["x-api-token"],
            "order": 3,
        }

    @parameterized.expand(
        [
            ("no field", {"value": {}}, []),
            ("empty list", {"value": {}, "secret_keys": []}, []),
            ("names", {"value": {}, "secret_keys": ["a", "b"]}, ["a", "b"]),
            ("non-list", {"value": {}, "secret_keys": "a"}, []),
            ("blank names dropped", {"value": {}, "secret_keys": ["a", "", None]}, ["a"]),
        ]
    )
    def test_secret_entry_names(self, _name: str, input_obj: dict, expected: list) -> None:
        assert secret_entry_names(input_obj) == expected

    def test_split_moves_only_the_named_entries(self) -> None:
        split = split_secret_entries(self._headers_input())

        assert split.public["value"] == {"Content-Type": "application/json"}
        assert split.secret["value"] == {"x-api-token": "tok_HqZ2NmVrTt"}
        # The names have to survive in the clear, or a read-back cannot tell which rows are secret.
        assert split.public["secret_keys"] == ["x-api-token"]

    def test_split_moves_the_bytecode_of_a_secret_entry(self) -> None:
        # Compiled bytecode embeds the literal value, so leaving it behind would keep the
        # credential readable in the unencrypted column.
        split = split_secret_entries(self._headers_input())

        assert split.public["bytecode"] == {"Content-Type": ["_H", 1, 32, "application/json"]}
        assert split.secret["bytecode"] == {"x-api-token": ["_H", 1, 32, "tok_HqZ2NmVrTt"]}

    def test_merge_rebuilds_the_input(self) -> None:
        original = self._headers_input()
        split = split_secret_entries(original)

        assert merge_secret_entries(split.public, split.secret) == original

    def test_recover_carries_over_an_untouched_entry(self) -> None:
        # The editor omits a secret entry it did not retype. Without recovery, saving an unrelated
        # header would drop the credential.
        incoming = {"value": {"Content-Type": "application/json"}, "secret_keys": ["x-api-token"]}
        stored = {"value": {"x-api-token": "tok_HqZ2NmVrTt"}}

        recovered = recover_secret_entries(incoming, stored)

        assert recovered["value"] == {"Content-Type": "application/json", "x-api-token": "tok_HqZ2NmVrTt"}

    def test_recover_keeps_a_rotated_entry(self) -> None:
        incoming = {"value": {"x-api-token": "tok_new"}, "secret_keys": ["x-api-token"]}
        stored = {"value": {"x-api-token": "tok_old"}}

        assert recover_secret_entries(incoming, stored)["value"] == {"x-api-token": "tok_new"}

    def test_recover_keeps_one_entry_while_rotating_another(self) -> None:
        # The whole reason per-entry storage exists: a whole-input secret cannot express this, so
        # rotating one credential used to mean overwriting the other with nothing.
        incoming = {"value": {"x-api-token": "tok_new"}, "secret_keys": ["x-api-token", "x-other"]}
        stored = {"value": {"x-api-token": "tok_old", "x-other": "other_kept"}}

        assert recover_secret_entries(incoming, stored)["value"] == {
            "x-api-token": "tok_new",
            "x-other": "other_kept",
        }

    @parameterized.expand(
        [
            ("nothing stored", None, ["x-api-token"]),
            ("stored empty", {"value": {"x-api-token": ""}}, ["x-api-token"]),
            ("stored value", {"value": {"x-api-token": "tok"}}, []),
        ]
    )
    def test_missing_secret_entries(self, _name: str, stored: dict | None, expected: list) -> None:
        incoming = {"value": {}, "secret_keys": ["x-api-token"]}

        assert missing_secret_entries(incoming, stored) == expected
