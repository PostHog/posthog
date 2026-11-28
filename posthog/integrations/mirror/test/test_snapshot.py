import datetime as dt
from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.integrations.mirror.snapshot import (
    ALL_KEYS_UNREADABLE,
    MirrorDelete,
    MirrorUpsert,
    TeamMismatch,
    UnmirrorableRow,
    read_snapshot,
    split_unreadable,
)
from posthog.models import Organization, Project, Team
from posthog.models.integration import Integration
from posthog.models.integration.auth_types import ANY

CIPHERTEXT = "gAAAAABfake-ciphertext-no-key-opens"


class TestSplitUnreadable(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "all_readable",
                {"access_token": "a", "nested": {"b": [1, "c"]}},
                {"access_token": "a", "nested": {"b": [1, "c"]}},
                (),
            ),
            ("top_level_ciphertext", {"api_key": CIPHERTEXT, "other": "x"}, {"other": "x"}, ("api_key",)),
            ("nested_dict_leaf", {"oauth": {"tokens": {"refresh": CIPHERTEXT}, "scope": "read"}}, {}, ("oauth",)),
            ("nested_list_leaf", {"keys": ["plain", {"k": CIPHERTEXT}]}, {}, ("keys",)),
            ("sorted_names", {"z": CIPHERTEXT, "a": CIPHERTEXT, "m": "ok"}, {"m": "ok"}, ("a", "z")),
            ("empty", {}, {}, ()),
            ("string_blob", CIPHERTEXT, {}, (ALL_KEYS_UNREADABLE,)),
            ("list_blob", ["a"], {}, (ALL_KEYS_UNREADABLE,)),
            ("null_blob", None, {}, (ALL_KEYS_UNREADABLE,)),
        ]
    )
    def test_split(
        self, _name: str, sensitive_config: object, readable: dict[str, Any], unreadable: tuple[str, ...]
    ) -> None:
        assert split_unreadable(sensitive_config) == (readable, unreadable)


class TestReadSnapshot(BaseTest):
    def _create(self, **fields: Any) -> Integration:
        return Integration.objects._with_auth(ANY).create(team=self.team, **{"kind": "slack", **fields})

    def test_live_row(self) -> None:
        row = self._create(
            integration_id="T1",
            config={"team": {"name": "Example"}},
            sensitive_config={"access_token": "fake-token"},
            errors="token expired",
            created_by=self.user,
            repository_cache=[{"name": "not-mirrored"}],
        )
        Integration.objects.filter(pk=row.pk).update(created_at=dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.UTC))
        Integration.objects.filter(pk=row.pk).update(config={"team": {"name": "Renamed"}})

        snapshot = read_snapshot(team_id=self.team.id, kind="slack", legacy_id=row.id)

        assert snapshot == MirrorUpsert(
            legacy_id=row.id,
            kind="slack",
            source_version=1,
            integration_id="T1",
            auth_type="oauth",
            is_source_row=False,
            config={"team": {"name": "Renamed"}},
            sensitive_config={"access_token": "fake-token"},
            legacy_unreadable_keys=(),
            errors="token expired",
            created_by_id=self.user.id,
            created_at="2024-01-02T03:04:05.000000+00:00",
        )
        assert "repository_cache" not in snapshot.to_body()

    @parameterized.expand(
        [
            ("default_auth_type", {}, "oauth", False),
            ("stored_auth_type", {"auth_type": "token"}, "token", False),
            ("source_row", {"auth_type": "token", "warehouse_source_type": "Slack"}, "token", True),
        ]
    )
    def test_effective_auth_type_and_source_marker(
        self, _name: str, config: dict[str, Any], auth_type: str, is_source_row: bool
    ) -> None:
        row = self._create(config=config)

        snapshot = read_snapshot(team_id=self.team.id, kind="slack", legacy_id=row.id)

        assert isinstance(snapshot, MirrorUpsert)
        assert (snapshot.auth_type, snapshot.is_source_row, snapshot.config) == (auth_type, is_source_row, config)

    @parameterized.expand(
        [
            ("nested_ciphertext_leaf", {"oauth": {"refresh_token": CIPHERTEXT}, "ok": "v"}, {"ok": "v"}, ("oauth",)),
            ("string_blob", "not-a-json-object", {}, (ALL_KEYS_UNREADABLE,)),
            ("list_blob", ["a", "b"], {}, (ALL_KEYS_UNREADABLE,)),
        ]
    )
    def test_unreadable_secrets_leave_the_blob(
        self, _name: str, stored: object, readable: dict[str, Any], unreadable: tuple[str, ...]
    ) -> None:
        row = self._create(sensitive_config=stored)

        snapshot = read_snapshot(team_id=self.team.id, kind="slack", legacy_id=row.id)

        assert isinstance(snapshot, MirrorUpsert)
        assert (snapshot.sensitive_config, snapshot.legacy_unreadable_keys) == (readable, unreadable)

    @parameterized.expand(
        [
            ("top_level", {"account_id": 2**53 + 1}),
            ("nested", {"accounts": [{"id": -(2**53) - 1}]}),
        ]
    )
    def test_integer_json_numbers_cannot_carry_is_refused(self, _name: str, config: dict[str, Any]) -> None:
        # Secret leaves load as strings, so only `config` can hold such an integer.
        row = self._create(config=config)

        with self.assertRaises(UnmirrorableRow):
            read_snapshot(team_id=self.team.id, kind="slack", legacy_id=row.id)

    def test_integer_a_double_holds_exactly_is_mirrored(self) -> None:
        row = self._create(config={"account_id": 2**60, "small": 2**53 - 1})

        snapshot = read_snapshot(team_id=self.team.id, kind="slack", legacy_id=row.id)

        assert isinstance(snapshot, MirrorUpsert)
        assert snapshot.config == {"account_id": 2**60, "small": 2**53 - 1}

    def test_deleted_row_is_a_tombstone_delete(self) -> None:
        row = self._create()
        legacy_id = row.id
        row.delete()

        assert read_snapshot(team_id=self.team.id, kind="slack", legacy_id=legacy_id) == MirrorDelete(
            legacy_id=legacy_id, kind="slack", tombstone=True
        )

    def test_row_of_another_team_is_refused(self) -> None:
        organization = Organization.objects.create(name="Other")
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
        other_team = Team.objects.create(id=project.id, project=project, organization=organization)
        row = Integration.objects.create(team=other_team, kind="slack", sensitive_config={"access_token": "x"})

        with self.assertRaises(TeamMismatch):
            read_snapshot(team_id=self.team.id, kind="slack", legacy_id=row.id)
