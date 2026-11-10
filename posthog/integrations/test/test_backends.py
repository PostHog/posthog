import time
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized, parameterized_class

from posthog.integrations import IntegrationManager, IntegrationPatch, IntegrationRecord, usages
from posthog.integrations.accessors import IntegrationReader
from posthog.integrations.backend.fake_backend import FakeBackend
from posthog.integrations.contracts import IntegrationConflict, IntegrationInUse, IntegrationNotFound, IntegrationUsage
from posthog.integrations.references import IntegrationReference
from posthog.integrations.testing import fake_integrations_backend
from posthog.models import Team
from posthog.models.integration import ANY, Integration
from posthog.models.integration.oauth import OauthIntegration

MARKER = "warehouse_source_type"

# name -> (kind, config). The name is also the external id.
ROWS: dict[str, tuple[str, dict[str, Any]]] = {
    "github_oauth": ("github", {"account": {"name": "octo"}}),
    "github_token": ("github", {"auth_type": "token"}),
    # `save()` drops a stored default auth type, but `QuerySet.update()` can still write one.
    "slack_stored_default": ("slack", {"auth_type": "oauth"}),
    "slack_null_auth_type": ("slack", {"auth_type": None}),
    "stripe_source": ("stripe", {"auth_type": "token", MARKER: "Stripe"}),
    "postgres": (
        "postgresql",
        {"host": "db", "user": "u", "port": 5432, "ratio": 1.0, "ssl": True, "label": "123", "empty": None},
    ),
}


def _refreshed_tokens(record: IntegrationRecord) -> IntegrationPatch:
    if record.config.get("fail_refresh"):
        return IntegrationPatch(errors="TOKEN_REFRESH_FAILED")
    return IntegrationPatch(sensitive_config_patch={"access_token": "new", "refresh_token": "r2"})


@parameterized_class(("backend",), [("django",), ("fake",)])
class TestBackendsBehaveTheSame(BaseTest):
    backend: str

    def setUp(self) -> None:
        super().setUp()
        self.refreshes: list[int] = []
        self.fake: FakeBackend | None = None
        if self.backend == "fake":
            self.fake = self.enterContext(fake_integrations_backend(token_refresher=self._count_refresh))
        else:
            self.enterContext(
                patch.object(OauthIntegration, "refresh_access_token", autospec=True, side_effect=self._django_refresh)
            )
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        self.ids = {name: self._seed(name, kind, config) for name, (kind, config) in ROWS.items()}
        self.other_id = self._seed("github_oauth", "github", {}, team=self.other_team)

    def _count_refresh(self, record: IntegrationRecord) -> IntegrationPatch:
        self.refreshes.append(record.id)
        return _refreshed_tokens(record)

    def _django_refresh(self, oauth: OauthIntegration) -> None:
        patch_ = self._count_refresh(oauth.integration)
        if patch_.errors:
            oauth.integration.errors = patch_.errors
        oauth.integration.sensitive_config = {**oauth.integration.sensitive_config, **patch_.sensitive_config_patch}
        oauth.integration.save()

    def _seed(
        self,
        name: str | None,
        kind: str,
        config: dict[str, Any],
        *,
        team: Team | None = None,
        sensitive_config: dict[str, Any] | None = None,
    ) -> int:
        team_id = (team or self.team).id
        if self.fake is not None:
            return self.fake.seed(
                team_id=team_id, kind=kind, external_id=name, config=config, sensitive_config=sensitive_config
            ).id
        row = Integration.objects._with_auth(ANY).create(
            team_id=team_id, kind=kind, integration_id=name, sensitive_config=sensitive_config or {}
        )
        Integration._base_manager.filter(id=row.id).update(config=config)
        return row.id

    def _stored(self, id: int, team: Team | None = None) -> IntegrationRecord:
        return IntegrationManager.any.with_source_rows().get((team or self.team).id, id)

    def _names(self, rows: list[IntegrationRecord]) -> list[str | None]:
        return [row.integration_id for row in rows]

    @parameterized.expand(
        [
            ("one_auth_type", lambda: IntegrationManager.github.oauth, ["github_oauth"]),
            ("non_default_auth_type", lambda: IntegrationManager.github.token, ["github_token"]),
            (
                "stored_and_null_default_auth_type",
                lambda: IntegrationManager.slack.oauth,
                ["slack_stored_default", "slack_null_auth_type"],
            ),
            ("kind_any_skips_source_rows", lambda: IntegrationManager.stripe.any, []),
            ("source_rows_only", lambda: IntegrationManager.source("stripe").token, ["stripe_source"]),
            ("every_kind", lambda: IntegrationManager.any, [n for n in ROWS if n != "stripe_source"]),
            ("every_kind_with_source_rows", lambda: IntegrationManager.any.with_source_rows(), list(ROWS)),
            (
                "kinds_default_auth_type",
                lambda: IntegrationManager.kinds("github", "postgresql"),
                ["github_oauth", "postgres"],
            ),
            (
                "kinds_any_auth_type",
                lambda: IntegrationManager.kinds("github", auth_types="any"),
                ["github_oauth", "github_token"],
            ),
        ]
    )
    def test_list_returns_the_rows_in_scope_oldest_first(
        self, _name: str, accessor: Callable[[], IntegrationReader], expected: list[str]
    ) -> None:
        rows = accessor().list(self.team.id)

        assert self._names(rows) == expected
        assert self._names(accessor().list(self.team.id, newest_first=True)) == expected[::-1]

    @parameterized.expand(
        [
            ("int", {"port": 5432}, True),
            ("int_equals_a_float", {"port": 5432.0}, True),
            ("float_equals_an_int", {"ratio": 1}, True),
            ("bool_is_not_an_int", {"ssl": 1}, False),
            ("int_is_not_a_bool", {"port": True}, False),
            ("bool", {"ssl": True}, True),
            ("string_is_not_an_int", {"label": 123}, False),
            ("string", {"label": "123"}, True),
            ("none_matches_a_json_null", {"empty": None}, True),
            ("none_does_not_match_a_missing_key", {"missing": None}, False),
            ("every_key_must_match", {"host": "db", "user": "other"}, False),
        ]
    )
    def test_where_compares_json_values(self, _name: str, where: dict[str, Any], expected: bool) -> None:
        accessor = IntegrationManager.postgresql.credentials

        assert accessor.exists(self.team.id, where=where) is expected
        assert (accessor.find(self.team.id, where=where) is not None) is expected

    @parameterized.expand(
        [
            ("both_teams_finds_the_oldest", ["own", "other"], "own"),
            ("other_team", ["other"], "other"),
            ("no_team", [], None),
        ]
    )
    def test_find_with_team_ids(self, _name: str, teams: list[str], expected: str | None) -> None:
        by_name = {"own": self.team.id, "other": self.other_team.id}
        row = IntegrationManager.github.oauth.find(team_ids=[by_name[t] for t in teams], external_id="github_oauth")

        assert (row.team_id if row else None) == (by_name[expected] if expected else None)

    @parameterized.expand(
        [("missing_id", lambda self: 10**9), ("not_a_number", lambda self: "abc"), ("none", lambda self: None)]
    )
    def test_get_raises_for_a_bad_id(self, _name: str, row_id: Callable[[Any], Any]) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.any.get(self.team.id, row_id(self))

    def test_get_reads_an_id_as_a_number_and_stays_in_the_team(self) -> None:
        row_id = self.ids["github_oauth"]

        assert IntegrationManager.github.oauth.get(self.team.id, str(row_id)).id == row_id  # type: ignore[arg-type]
        assert list(IntegrationManager.github.oauth.get_many(self.team.id, [row_id, self.other_id, 10**9])) == [row_id]
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.get(self.team.id, self.other_id)

    def test_cross_team_reads(self) -> None:
        accessor = IntegrationManager.github.oauth

        assert {row.team_id for row in accessor.list_by_external_id("github_oauth")} == {
            self.team.id,
            self.other_team.id,
        }
        assert [row.team_id for row in accessor.list_by_external_id("github_oauth", team_ids=[self.other_team.id])] == [
            self.other_team.id
        ]
        assert (accessor.count_by_external_id("github_oauth"), accessor.exists_by_external_id("github_token")) == (
            2,
            False,
        )
        assert accessor.get_by_external_id("github_oauth", self.other_id).team_id == self.other_team.id
        with self.assertRaises(IntegrationNotFound):
            accessor.get_by_external_id("github_token", self.other_id)

    @parameterized.expand(
        [
            (
                "default_auth_type",
                lambda: IntegrationManager.github.oauth,
                {"account": {"name": "octo"}},
                {"account": {"name": "octo"}},
                "oauth",
                "octo",
            ),
            (
                "non_default_auth_type",
                lambda: IntegrationManager.github.token,
                {},
                {"auth_type": "token"},
                "token",
                "ID: new",
            ),
            (
                "credentials_kind",
                lambda: IntegrationManager.postgresql.credentials,
                {"host": "db", "user": "u"},
                {"host": "db", "user": "u"},
                "credentials",
                "u@db",
            ),
        ]
    )
    def test_create_returns_the_stored_row(
        self,
        _name: str,
        accessor: Callable[[], Any],
        config: dict[str, Any],
        stored_config: dict[str, Any],
        auth_type: str,
        display_name: str,
    ) -> None:
        row = accessor().create(
            self.team.id,
            external_id="new",
            config=config,
            sensitive_config={"access_token": "t"},
            created_by_id=self.user.id,
        )

        stored = self._stored(row.id)
        for record in (row, stored):
            assert (record.config, record.sensitive_config, record.errors, record.created_by_id) == (
                stored_config,
                {"access_token": "t"},
                "",
                self.user.id,
            )
            assert (record.auth_type, record.display_name, record.access_token) == (auth_type, display_name, "t")
            assert record.reference == str(IntegrationReference.from_legacy_id(row.id))

    @parameterized.expand(
        [
            ("same_scope", lambda: IntegrationManager.github.oauth, "github_oauth", {}),
            ("other_auth_type", lambda: IntegrationManager.github.token, "github_oauth", {}),
            ("source_row_of_the_kind", lambda: IntegrationManager.stripe.token, "stripe_source", {}),
        ]
    )
    def test_create_raises_conflict_on_the_unique_key(
        self, _name: str, accessor: Callable[[], Any], external_id: str, config: dict[str, Any]
    ) -> None:
        with self.assertRaises(IntegrationConflict):
            accessor().create(self.team.id, external_id=external_id, config=config)

        assert len(IntegrationManager.any.with_source_rows().list(self.team.id, external_id=external_id)) == 1

    def test_rows_without_an_external_id_never_conflict(self) -> None:
        first = IntegrationManager.github.oauth.create(self.team.id, external_id=None, config={})
        second = IntegrationManager.github.oauth.create(self.team.id, external_id=None, config={})

        assert first.id != second.id

    def test_upsert_creates_then_replaces_and_keeps_the_creator(self) -> None:
        accessor = IntegrationManager.github.token
        row, created = accessor.upsert(self.team.id, "new", config={"a": 1}, created_by_id=self.user.id)
        again, created_again = accessor.upsert(self.team.id, "new", config={"b": 2}, sensitive_config={"s": 1})

        stored = self._stored(row.id)
        assert (created, created_again, again.id) == (True, False, row.id)
        assert (stored.config, stored.sensitive_config, stored.created_by_id) == (
            {"b": 2, "auth_type": "token"},
            # The encrypted field stores every secret value as a string.
            {"s": "1"},
            self.user.id,
        )

    @parameterized.expand(
        [
            ("other_auth_type", lambda: IntegrationManager.github.token, "github_oauth", {}),
            ("source_row", lambda: IntegrationManager.stripe.token, "stripe_source", {}),
        ]
    )
    def test_upsert_raises_on_a_row_out_of_scope(
        self, _name: str, accessor: Callable[[], Any], external_id: str, config: dict[str, Any]
    ) -> None:
        before = self._stored(self.ids[external_id]).config

        with self.assertRaises(IntegrationConflict):
            accessor().upsert(self.team.id, external_id, config=config)

        assert self._stored(self.ids[external_id]).config == before

    @parameterized.expand(
        [
            (
                "merge_and_remove",
                {"config_patch": {"login": "x"}, "config_remove": ["account"]},
                {"login": "x"},
                "",
                {},
            ),
            (
                "errors_and_secrets",
                {"errors": "BROKEN", "sensitive_config_patch": {"s": "x"}},
                {"account": {"name": "octo"}},
                "BROKEN",
                {"s": "x"},
            ),
            ("nothing", {}, {"account": {"name": "octo"}}, "", {}),
        ]
    )
    def test_update_applies_the_patch(
        self,
        _name: str,
        kwargs: dict[str, Any],
        config: dict[str, Any],
        errors: str,
        sensitive_config: dict[str, Any],
    ) -> None:
        row_id = self.ids["github_oauth"]

        updated = IntegrationManager.github.oauth.update(self.team.id, row_id, **kwargs)

        stored = self._stored(row_id)
        for record in (updated, stored):
            assert (record.config, record.errors, record.sensitive_config) == (config, errors, sensitive_config)

    @parameterized.expand(
        [
            ("int_to_bool", 1, True),
            ("bool_to_int", True, 1),
            ("int_to_float", 1, 1.0),
        ]
    )
    def test_update_writes_a_value_of_another_json_type(self, _name: str, before: object, after: object) -> None:
        row_id = self.ids["github_oauth"]
        IntegrationManager.github.oauth.update(self.team.id, row_id, config_patch={"flag": before})

        IntegrationManager.github.oauth.update(self.team.id, row_id, config_patch={"flag": after})

        saved = self._stored(row_id).config["flag"]
        assert (saved, type(saved)) == (after, type(after))

    def test_update_raises_for_a_row_out_of_scope(self) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.update(self.team.id, self.ids["github_token"], errors="")

    @parameterized.expand(
        [
            ("changes_every_team", IntegrationPatch(config_patch={"suspended": True}), [2]),
            ("second_write_changes_nothing", IntegrationPatch(config_patch={"suspended": True}), [2, 0]),
            ("errors_only", IntegrationPatch(errors="SUSPENDED"), [2, 0]),
            ("empty_patch", IntegrationPatch(), [0]),
        ]
    )
    def test_update_by_external_id_counts_the_changed_rows(
        self, _name: str, row_patch: IntegrationPatch, expected: list[int]
    ) -> None:
        accessor = IntegrationManager.github.oauth

        counts = [accessor.update_by_external_id("github_oauth", row_patch) for _ in expected]

        assert counts == expected
        assert "suspended" not in self._stored(self.ids["github_token"]).config
        if row_patch.errors:
            assert self._stored(self.other_id, self.other_team).errors == "SUSPENDED"

    def test_delete_checks_usages_and_stays_in_scope(self) -> None:
        row_id = self.ids["github_oauth"]
        usage = IntegrationUsage(type="workflow", id="1", name="Flow")

        with (
            patch.object(usages, "_registered", []),
            patch.object(usages, "_product_providers", [lambda t, i: [usage] if i == row_id else []]),
        ):
            with self.assertRaises(IntegrationInUse):
                IntegrationManager.github.oauth.delete(self.team.id, row_id)
            with self.assertRaises(IntegrationNotFound):
                IntegrationManager.github.oauth.delete(self.team.id, self.ids["github_token"])
            IntegrationManager.github.oauth.delete(self.team.id, row_id, ignore_usages=True)

        assert not IntegrationManager.github.any.exists(self.team.id, external_id="github_oauth")
        assert IntegrationManager.github.any.exists(self.team.id, external_id="github_token")

    def test_delete_by_external_id_reaches_every_team(self) -> None:
        assert IntegrationManager.github.oauth.delete_by_external_id("github_oauth") == 2
        assert IntegrationManager.github.oauth.count_by_external_id("github_oauth") == 0
        assert IntegrationManager.github.token.exists(self.team.id, external_id="github_token")

    @parameterized.expand(
        [
            ("expired", 800, None, False, "new", ""),
            ("fresh", 10, None, False, "old", ""),
            ("fresh_but_stale_for_the_caller", 10, "old", False, "new", ""),
            ("another_worker_rotated_the_token", 10, "older", False, "old", ""),
            ("failed_refresh_sets_errors", 800, None, True, "old", "TOKEN_REFRESH_FAILED"),
        ]
    )
    def test_refresh_access_token(
        self,
        _name: str,
        refreshed_ago: int,
        stale_access_token: str | None,
        fail: bool,
        token: str,
        errors: str,
    ) -> None:
        config: dict[str, Any] = {"expires_in": 900, "refreshed_at": int(time.time()) - refreshed_ago}
        if fail:
            config["fail_refresh"] = True
        row_id = self._seed(
            "resend-account", "resend", config, sensitive_config={"access_token": "old", "refresh_token": "r1"}
        )

        row = IntegrationManager.resend.oauth.refresh_access_token(
            self.team.id, row_id, stale_access_token=stale_access_token
        )

        stored = self._stored(row_id)
        assert self.refreshes == ([row_id] if token == "new" or fail else [])
        for record in (row, stored):
            assert (record.access_token, record.errors) == (token, errors)
