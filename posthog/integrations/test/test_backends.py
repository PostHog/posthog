import time
import tempfile
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized, parameterized_class

from posthog.integrations import CrossTeamFilter, IntegrationManager, IntegrationPatch, IntegrationRecord, usages
from posthog.integrations.accessors import IntegrationReader
from posthog.integrations.backend import use_backend
from posthog.integrations.backend.fake_backend import FakeBackend
from posthog.integrations.backend.service_backend import ServiceBackend
from posthog.integrations.contracts import (
    IntegrationConflict,
    IntegrationInUse,
    IntegrationNotFound,
    IntegrationUsage,
    RepositoryCache,
)
from posthog.integrations.references import IntegrationReference
from posthog.integrations.test.credentials_service_stub import CredentialsServiceStub, write_signing_key
from posthog.integrations.testing import fake_integrations_backend
from posthog.models import Team
from posthog.models.integration import ANY, Integration, UndecryptedIntegrationSecretError
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


@parameterized_class(("backend",), [("django",), ("fake",), ("service",)])
class TestBackendsBehaveTheSame(BaseTest):
    backend: str

    def setUp(self) -> None:
        super().setUp()
        self.refreshes: list[int] = []
        self.fake: FakeBackend | None = None
        if self.backend == "fake":
            self.fake = self.enterContext(fake_integrations_backend(token_refresher=self._count_refresh))
        elif self.backend == "service":
            self.fake = FakeBackend(token_refresher=self._count_refresh)
            key_path, public_key = write_signing_key(self.enterContext(tempfile.TemporaryDirectory()))
            self.enterContext(
                override_settings(
                    CREDENTIALS_SERVICE_URL="http://credentials-service.test",
                    CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=key_path,
                )
            )
            self.enterContext(
                use_backend(ServiceBackend(session=cast(Any, CredentialsServiceStub(self.fake, public_key))))
            )
        else:
            self.enterContext(
                patch.object(
                    OauthIntegration,
                    "token_refresh_patch",
                    autospec=True,
                    side_effect=lambda oauth: self._count_refresh(oauth.integration),
                )
            )
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        self.ids = {name: self._seed(name, kind, config) for name, (kind, config) in ROWS.items()}
        self.other_id = self._seed("github_oauth", "github", {}, team=self.other_team)

    def _skip_without_service_route(self) -> None:
        if self.backend == "service":
            self.skipTest("The credentials service has no route for this operation yet")

    def _count_refresh(self, record: IntegrationRecord) -> IntegrationPatch:
        self.refreshes.append(record.id)
        return _refreshed_tokens(record)

    def _seed(
        self,
        name: str | None,
        kind: str,
        config: dict[str, Any],
        *,
        team: Team | None = None,
        sensitive_config: dict[str, Any] | None = None,
        created_by_id: int | None = None,
    ) -> int:
        team_id = (team or self.team).id
        if self.fake is not None:
            return self.fake.seed(
                team_id=team_id,
                kind=kind,
                external_id=name,
                config=config,
                sensitive_config=sensitive_config,
                created_by_id=created_by_id,
            ).id
        row = Integration.objects._with_auth(ANY).create(
            team_id=team_id,
            kind=kind,
            integration_id=name,
            sensitive_config=sensitive_config or {},
            created_by_id=created_by_id,
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

    def _seed_cross_team_rows(self) -> dict[str, int]:
        # Seeded in this order, so oldest first is the order of this list.
        seeds: list[tuple[str, str, dict[str, Any], Team, int | None]] = [
            ("a", "email", {"provider": "ses", "domain": "one.example.com", "verified": True}, self.team, self.user.id),
            ("b", "email", {"provider": "ses", "domain": "two.example.com"}, self.team, None),
            ("c", "email", {"provider": "SES", "domain": "one.example.com", "verified": True}, self.other_team, None),
            (
                "d",
                "email",
                {"provider": "mailjet", "domain": "two.example.com", "port": 1},
                self.other_team,
                self.user.id,
            ),
            ("slack_ses", "slack", {"provider": "ses", "domain": "one.example.com"}, self.team, self.user.id),
            ("other_octo", "github", {"account": {"name": "OCTO"}}, self.other_team, None),
            ("flat_account", "github", {"account": "octo"}, self.other_team, None),
        ]
        return {
            name: self._seed(name, kind, config, team=team, created_by_id=by) for name, kind, config, team, by in seeds
        }

    @parameterized.expand(
        [
            ("no_filter", "email", lambda t, ids: CrossTeamFilter(), ["a", "b", "c", "d"]),
            ("team_ids", "email", lambda t, ids: CrossTeamFilter(team_ids=[t.other_team.id]), ["c", "d"]),  # type: ignore[arg-type]
            ("empty_team_ids", "email", lambda t, ids: CrossTeamFilter(team_ids=()), []),
            ("exclude_team_ids", "email", lambda t, ids: CrossTeamFilter(exclude_team_ids=(t.team.id,)), ["c", "d"]),
            ("created_by_ids", "email", lambda t, ids: CrossTeamFilter(created_by_ids=(t.user.id,)), ["a", "d"]),
            ("empty_created_by_ids", "email", lambda t, ids: CrossTeamFilter(created_by_ids=()), []),
            ("external_id", "email", lambda t, ids: CrossTeamFilter(external_id="c"), ["c"]),
            ("where_is_case_sensitive", "email", lambda t, ids: CrossTeamFilter(where={"provider": "ses"}), ["a", "b"]),
            (
                "where_in",
                "email",
                lambda t, ids: CrossTeamFilter(where_in={"domain": ("one.example.com", "nowhere.example.com")}),
                ["a", "c"],
            ),
            ("where_in_empty", "email", lambda t, ids: CrossTeamFilter(where_in={"domain": ()}), []),
            ("where_in_int_equals_a_float", "email", lambda t, ids: CrossTeamFilter(where_in={"port": (1.0,)}), ["d"]),
            ("where_in_string_is_not_an_int", "email", lambda t, ids: CrossTeamFilter(where_in={"port": ("1",)}), []),
            ("where_in_bool_is_not_an_int", "email", lambda t, ids: CrossTeamFilter(where_in={"port": (True,)}), []),
            (
                "where_iexact",
                "email",
                lambda t, ids: CrossTeamFilter(where_iexact={"provider": "Ses"}),
                ["a", "b", "c"],
            ),
            (
                "where_iexact_nested_key",
                "github",
                lambda t, ids: CrossTeamFilter(where_iexact={"account.name": "Octo"}),
                ["github_oauth", "other_octo"],
            ),
            ("has_config_key", "email", lambda t, ids: CrossTeamFilter(has_config_key="verified"), ["a", "c"]),
            (
                "every_field_with_and",
                "email",
                lambda t, ids: CrossTeamFilter(
                    where={"verified": True},
                    where_in={"domain": ("one.example.com",)},
                    exclude_team_ids=(t.team.id,),
                    has_config_key="provider",
                ),
                ["c"],
            ),
            ("newest_first", "email", lambda t, ids: CrossTeamFilter(newest_first=True), ["d", "c", "b", "a"]),
            ("limit", "email", lambda t, ids: CrossTeamFilter(limit=2), ["a", "b"]),
            ("after_id", "email", lambda t, ids: CrossTeamFilter(after_id=ids["b"]), ["c", "d"]),
            (
                "newest_first_page",
                "email",
                lambda t, ids: CrossTeamFilter(newest_first=True, after_id=ids["c"], limit=1),
                ["b"],
            ),
        ]
    )
    def test_list_across_teams(
        self,
        _name: str,
        kind: str,
        cross_team_filter: Callable[[Any, dict[str, int]], CrossTeamFilter],
        expected: list[str],
    ) -> None:
        ids = self._seed_cross_team_rows()
        accessor = IntegrationManager.kinds(kind, auth_types="any")

        rows = accessor.list_across_teams(cross_team_filter(self, ids))

        assert self._names(rows) == expected

    @parameterized.expand(
        [
            ("one_auth_type", lambda: IntegrationManager.github.token, ["github_token"]),
            ("skips_source_rows", lambda: IntegrationManager.stripe.any, []),
            ("with_source_rows", lambda: IntegrationManager.stripe.any.with_source_rows(), ["stripe_source"]),
            ("source_rows_only", lambda: IntegrationManager.source("stripe").any, ["stripe_source"]),
        ]
    )
    def test_list_across_teams_stays_in_the_scope(
        self, _name: str, accessor: Callable[[], IntegrationReader], expected: list[str]
    ) -> None:
        self._seed("github_token", "github", {"auth_type": "token"}, team=self.other_team)

        rows = accessor().list_across_teams(CrossTeamFilter(team_ids=(self.team.id,)))

        assert self._names(rows) == expected

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

    def test_upsert_creates_then_replaces_clears_errors_and_keeps_the_creator(self) -> None:
        accessor = IntegrationManager.github.token
        row, created = accessor.upsert(self.team.id, "new", config={"a": 1}, created_by_id=self.user.id)
        accessor.update(self.team.id, row.id, errors="TOKEN_REFRESH_FAILED")
        again, created_again = accessor.upsert(self.team.id, "new", config={"b": 2}, sensitive_config={"s": 1})

        stored = self._stored(row.id)
        assert (created, created_again, again.id) == (True, False, row.id)
        assert (again.errors, again.created_by_id) == ("", self.user.id)
        assert (stored.config, stored.sensitive_config, stored.errors, stored.created_by_id) == (
            {"b": 2, "auth_type": "token"},
            # The encrypted field stores every secret value as a string.
            {"s": "1"},
            "",
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

    def test_update_leaves_an_unreadable_secret_field_alone(self) -> None:
        # An undecryptable secret field reads back as a raw string, not a dict.
        row_id = self._seed("unreadable", "github", {})
        if self.fake is not None:
            self.fake._rows[row_id] = replace(self.fake._rows[row_id], sensitive_config="raw")  # type: ignore[arg-type]
        else:
            Integration._base_manager.filter(id=row_id).update(sensitive_config="raw")

        updated = IntegrationManager.github.oauth.update(self.team.id, row_id, config_patch={"login": "x"})

        stored = self._stored(row_id)
        for record in (updated, stored):
            assert record.config == {"login": "x"}
            if self.backend == "service":
                # The service never returns a raw secret. A read of an unreadable secret raises.
                with self.assertRaises(UndecryptedIntegrationSecretError):
                    _ = record.access_token
            else:
                sensitive_config: object = record.sensitive_config
                assert sensitive_config == "raw"

    @parameterized.expand(
        [
            ("moves", "github_oauth", "moved", "moved"),
            ("same_id_writes_nothing", "github_oauth", "github_oauth", "github_oauth"),
            # Postgres checks the unique key across auth types, so the token row blocks the oauth row.
            ("taken_by_a_row_of_another_auth_type", "github_oauth", "github_token", IntegrationConflict),
            ("row_out_of_scope", "github_token", "moved", IntegrationNotFound),
        ]
    )
    def test_change_external_id(
        self, _name: str, row_name: str, external_id: str, expected: str | type[Exception]
    ) -> None:
        self._skip_without_service_route()
        row_id = self.ids[row_name]

        if isinstance(expected, type):
            with self.assertRaises(expected):
                IntegrationManager.github.oauth.change_external_id(self.team.id, row_id, external_id)
            assert self._stored(row_id).integration_id == row_name
            return
        row = IntegrationManager.github.oauth.change_external_id(self.team.id, row_id, external_id)

        assert (row.integration_id, self._stored(row_id).integration_id) == (expected, expected)
        # The row of the other team keeps its external id.
        assert self._stored(self.other_id, self.other_team).integration_id == "github_oauth"

    def test_change_external_id_stays_in_the_team(self) -> None:
        self._skip_without_service_route()
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.change_external_id(self.other_team.id, self.ids["github_oauth"], "x")

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

    @parameterized.expand(
        [
            ("changes_the_unverified_rows", {"domain": "a.com"}, ["mixed_a", "verified_a"], ["mixed_a"]),
            ("second_key_narrows", {"domain": "a.com", "verified": True}, ["verified_a"], []),
            ("no_match", {"domain": "c.com"}, [], []),
        ]
    )
    def test_update_where_patches_the_matching_rows_of_the_team(
        self, _name: str, where: dict[str, Any], matched: list[str], changed: list[str]
    ) -> None:
        self._skip_without_service_route()
        seeds: list[tuple[str, dict[str, Any]]] = [
            ("mixed_a", {"domain": "a.com", "verified": False}),
            ("verified_a", {"domain": "a.com", "verified": True}),
            ("other_domain", {"domain": "b.com"}),
            ("token_a", {"domain": "a.com", "auth_type": "token"}),
        ]
        for name, config in seeds:
            self.ids[name] = self._seed(name, "github", config)
        other_team_row = self._seed("other_team_a", "github", {"domain": "a.com"}, team=self.other_team)

        result = IntegrationManager.github.oauth.update_where(
            self.team.id, where=where, patch=IntegrationPatch(config_patch={"verified": True})
        )

        assert self._names(list(result.records)) == matched
        assert result.changed_ids == {self.ids[name] for name in changed}
        assert all(record.config["verified"] is True for record in result.records)
        assert self._stored(self.ids["other_domain"]).config == {"domain": "b.com"}
        assert "verified" not in self._stored(self.ids["token_a"]).config
        assert "verified" not in self._stored(other_team_row, self.other_team).config

    def test_update_where_needs_a_filter(self) -> None:
        with self.assertRaises(ValueError):
            IntegrationManager.github.oauth.update_where(self.team.id, where={}, patch=IntegrationPatch(errors=""))

    def test_repository_cache_round_trip_keeps_the_config(self) -> None:
        self._skip_without_service_route()
        accessor = IntegrationManager.github.oauth
        row_id = self.ids["github_oauth"]
        first, second = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        assert accessor.get_repository_cache(self.team.id, row_id) == RepositoryCache(repositories=[], updated_at=None)

        accessor.set_repository_cache(self.team.id, row_id, repositories=[{"id": 1}], updated_at=first)
        accessor.update(self.team.id, row_id, config_patch={"login": "x"})
        # None keeps the stored list and moves only the fetch time.
        accessor.set_repository_cache(self.team.id, row_id, repositories=None, updated_at=second)

        assert accessor.get_repository_cache(self.team.id, row_id) == RepositoryCache(
            repositories=[{"id": 1}], updated_at=second
        )
        assert self._stored(row_id).config == {"account": {"name": "octo"}, "login": "x"}

    @parameterized.expand([("get",), ("set",)])
    def test_repository_cache_stays_in_scope(self, operation: str) -> None:
        self._skip_without_service_route()
        with self.assertRaises(IntegrationNotFound):
            if operation == "get":
                IntegrationManager.github.oauth.get_repository_cache(self.team.id, self.ids["github_token"])
            else:
                IntegrationManager.github.oauth.set_repository_cache(
                    self.other_team.id, self.ids["github_oauth"], repositories=[], updated_at=datetime.now(tz=UTC)
                )

    def test_expire_repository_cache_by_external_id_reaches_every_team(self) -> None:
        self._skip_without_service_route()
        accessor = IntegrationManager.github.oauth
        fetched = datetime(2026, 1, 1, tzinfo=UTC)
        for team, row_id in ((self.team, self.ids["github_oauth"]), (self.other_team, self.other_id)):
            accessor.set_repository_cache(team.id, row_id, repositories=[{"id": 1}], updated_at=fetched)
        IntegrationManager.github.token.set_repository_cache(
            self.team.id, self.ids["github_token"], repositories=[], updated_at=fetched
        )

        assert accessor.expire_repository_cache_by_external_id("github_oauth") == 2

        for team, row_id in ((self.team, self.ids["github_oauth"]), (self.other_team, self.other_id)):
            assert accessor.get_repository_cache(team.id, row_id) == RepositoryCache(
                repositories=[{"id": 1}], updated_at=None
            )
        token_cache = IntegrationManager.github.token.get_repository_cache(self.team.id, self.ids["github_token"])
        assert token_cache.updated_at == fetched

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

    @parameterized.expand(
        [
            ("every_team", lambda: IntegrationManager.github.oauth, ["github_oauth"], {"github_oauth": 2}),
            ("scope_skips_other_auth_types", lambda: IntegrationManager.github.token, ["github_oauth"], {}),
            (
                "ids_without_rows_are_left_out",
                lambda: IntegrationManager.github.any,
                ["github_token", "none"],
                {"github_token": 1},
            ),
            ("no_ids", lambda: IntegrationManager.github.oauth, [], {}),
        ]
    )
    def test_count_by_external_ids(
        self, _name: str, accessor: Callable[[], Any], external_ids: list[str], expected: dict[str, int]
    ) -> None:
        self._skip_without_service_route()
        assert accessor().count_by_external_ids(external_ids) == expected

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
        self._skip_without_service_route()
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

    @parameterized.expand(
        [
            ("row_without_a_token", None, "new"),
            ("row_with_a_token", "old", "old"),
        ]
    )
    def test_refresh_access_token_reads_an_empty_stale_token_as_no_token(
        self, _name: str, stored_token: str | None, token: str
    ) -> None:
        self._skip_without_service_route()
        sensitive_config: dict[str, Any] = {"refresh_token": "r1"}
        if stored_token is not None:
            sensitive_config["access_token"] = stored_token
        row_id = self._seed(
            "resend-account",
            "resend",
            {"expires_in": 900, "refreshed_at": int(time.time())},
            sensitive_config=sensitive_config,
        )

        row = IntegrationManager.resend.oauth.refresh_access_token(self.team.id, row_id, stale_access_token="")

        assert (row.access_token, self._stored(row_id).access_token) == (token, token)
