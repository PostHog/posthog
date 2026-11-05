import time
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.integrations import IntegrationManager, register_source_kinds, register_usage_provider, usages
from posthog.integrations.accessors import AuthAccessor, IntegrationReader, OAuthAccessor, SourceRows
from posthog.integrations.contracts import (
    IntegrationConflict,
    IntegrationInUse,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    IntegrationUsage,
    UnknownIntegrationKind,
    UnsupportedAuthType,
    UnsupportedIntegrationFilter,
)
from posthog.integrations.enums import AuthType
from posthog.models import Team
from posthog.models.integration import ANY, Integration, auth_types
from posthog.models.integration.auth_types import default_auth_type, kind_auth_types
from posthog.models.integration.model import IntegrationQuerySet
from posthog.models.integration.oauth import OauthIntegration

MARKER = "warehouse_source_type"

# name -> (kind, config). The name is also the external id.
ROWS: dict[str, tuple[str, dict[str, Any]]] = {
    "github_oauth": ("github", {"account": {"name": "a"}}),
    "github_token": ("github", {"auth_type": "token", "account": {"name": "a"}}),
    "slack_oauth": ("slack", {}),
    "stripe_oauth": ("stripe", {}),
    "stripe_token": ("stripe", {"auth_type": "token"}),
    "stripe_source": ("stripe", {"auth_type": "token", MARKER: "Stripe"}),
    "postgres": ("postgresql", {"host": "db.example.com"}),
    "postgres_source": ("postgresql", {"host": "db.example.com", MARKER: "Postgres"}),
    "ably_source": ("ably", {MARKER: "Ably"}),
}
SOURCE_ROWS = {name for name, (_kind, config) in ROWS.items() if MARKER in config}


@contextmanager
def _usage_providers(*providers: usages.UsageProvider) -> Iterator[None]:
    with patch.object(usages, "_registered", []), patch.object(usages, "_product_providers", list(providers)):
        yield


class TestIntegrationAccessors(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.rows = {
            name: Integration.objects._with_auth(ANY).create(
                team=self.team, kind=kind, integration_id=name, config=config
            )
            for name, (kind, config) in ROWS.items()
        }
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        self.other_row = Integration.objects._with_auth(ANY).create(
            team=self.other_team, kind="github", integration_id="github_oauth", config={}
        )

    def _names(self, rows: Iterable[IntegrationRecord]) -> set[str]:
        return {row.integration_id for row in rows if row.team_id == self.team.id and row.integration_id}

    @parameterized.expand(
        [
            ("single_auth_default", lambda: IntegrationManager.github.oauth, {"github_oauth"}),
            ("single_auth_non_default", lambda: IntegrationManager.github.token, {"github_token"}),
            ("kind_any", lambda: IntegrationManager.github.any, {"github_oauth", "github_token"}),
            ("skips_source_rows", lambda: IntegrationManager.stripe.token, {"stripe_token"}),
            ("kind_any_skips_source_rows", lambda: IntegrationManager.stripe.any, {"stripe_oauth", "stripe_token"}),
            ("credentials_default", lambda: IntegrationManager.postgresql.credentials, {"postgres"}),
            ("everything_but_source_rows", lambda: IntegrationManager.any, set(ROWS) - SOURCE_ROWS),
            ("everything_with_source_rows", lambda: IntegrationManager.any.with_source_rows(), set(ROWS)),
            (
                "kind_any_with_source_rows",
                lambda: IntegrationManager.stripe.any.with_source_rows(),
                {"stripe_oauth", "stripe_token", "stripe_source"},
            ),
            ("source_of_a_catalogue_kind", lambda: IntegrationManager.source("stripe").token, {"stripe_source"}),
            ("source_any", lambda: IntegrationManager.source("stripe").any, {"stripe_source"}),
            ("source_of_a_registered_kind", lambda: IntegrationManager.source("ably").token, {"ably_source"}),
            ("source_other_auth_type", lambda: IntegrationManager.source("ably").credentials, set()),
            (
                "several_kinds_default_auth_type_by_default",
                lambda: IntegrationManager.kinds("github", "slack"),
                {"github_oauth", "slack_oauth"},
            ),
            (
                "several_kinds_any_auth_type",
                lambda: IntegrationManager.kinds("github", "slack", auth_types="any"),
                {"github_oauth", "github_token", "slack_oauth"},
            ),
            # The source rows join the scope, and the auth type filter still applies to them.
            (
                "several_kinds_default_auth_type_with_source_rows",
                lambda: IntegrationManager.kinds("stripe", "postgresql").with_source_rows(),
                {"stripe_oauth", "postgres", "postgres_source"},
            ),
            (
                "several_kinds_any_auth_type_with_source_rows",
                lambda: IntegrationManager.kinds("stripe", auth_types="any").with_source_rows(),
                {"stripe_oauth", "stripe_token", "stripe_source"},
            ),
            (
                "several_kinds_default_auth_type",
                lambda: IntegrationManager.kinds("github", "stripe", "postgresql", auth_types="default"),
                {"github_oauth", "stripe_oauth", "postgres"},
            ),
            (
                "several_kinds_listed_auth_types",
                lambda: IntegrationManager.kinds("github", "stripe", "postgresql", auth_types=[AuthType.TOKEN]),
                {"github_token", "stripe_token"},
            ),
        ]
    )
    def test_list_returns_only_rows_in_scope(
        self, _name: str, accessor: Callable[[], IntegrationReader], expected: set[str]
    ) -> None:
        assert self._names(accessor().list(self.team.id)) == expected

    @parameterized.expand(
        [
            ("other_auth_type", lambda: IntegrationManager.github.oauth, "github_token"),
            ("source_row_through_named_accessor", lambda: IntegrationManager.stripe.any, "stripe_source"),
            ("named_row_through_source_accessor", lambda: IntegrationManager.source("stripe").token, "stripe_token"),
            ("other_kind", lambda: IntegrationManager.slack.oauth, "github_oauth"),
            ("source_row_through_any", lambda: IntegrationManager.any, "stripe_source"),
            ("other_auth_type_through_kinds", lambda: IntegrationManager.kinds("github"), "github_token"),
        ]
    )
    def test_get_raises_for_a_row_out_of_scope(
        self, _name: str, accessor: Callable[[], IntegrationReader], row_name: str
    ) -> None:
        with self.assertRaises(IntegrationNotFound):
            accessor().get(self.team.id, self.rows[row_name].id)

    @parameterized.expand([("missing_id", 10**9), ("not_a_number", "abc"), ("none", None)])
    def test_get_raises_for_a_bad_id(self, _name: str, row_id: Any) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.any.get(self.team.id, row_id)

    def test_a_stored_default_auth_type_reads_as_the_default(self) -> None:
        row = self.rows["github_oauth"]
        # `QuerySet.update()` skips `save()`, so it can store the default auth type of the kind.
        Integration._base_manager.filter(id=row.id).update(config={"auth_type": "oauth"})

        assert IntegrationManager.github.oauth.get(self.team.id, row.id).id == row.id
        assert self._names(IntegrationManager.kinds("github", auth_types="default").list(self.team.id)) == {
            "github_oauth"
        }
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.token.get(self.team.id, row.id)

    def test_get_does_not_cross_teams(self) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.get(self.team.id, self.other_row.id)

        assert IntegrationManager.github.oauth.get(self.other_team.id, self.other_row.id) == self.other_row

    def test_get_many_drops_ids_out_of_scope(self) -> None:
        ids = [self.rows["github_oauth"].id, self.rows["github_token"].id, self.other_row.id, 10**9]

        assert IntegrationManager.github.oauth.get_many(self.team.id, ids) == {
            self.rows["github_oauth"].id: self.rows["github_oauth"]
        }

    @parameterized.expand(
        [
            ("external_id", {"external_id": "github_token"}, "github_token"),
            ("nested_config_value", {"where": {"account": {"name": "a"}}}, None),
            ("scalar_config_value", {"where": {"auth_type_hint": None}}, None),
            ("oldest_without_filters", {}, "github_oauth"),
            ("no_match", {"external_id": "missing"}, None),
        ]
    )
    def test_find(self, _name: str, kwargs: dict[str, Any], expected: str | None) -> None:
        if isinstance(next(iter(kwargs.get("where", {}).values()), None), dict):
            with self.assertRaises(UnsupportedIntegrationFilter):
                IntegrationManager.github.any.find(self.team.id, **kwargs)
            return
        row = IntegrationManager.github.any.find(self.team.id, **kwargs)

        assert (row.integration_id if row else None) == expected

    @parameterized.expand(
        [
            ("string", {"host": "db.example.com"}, True),
            ("string_mismatch", {"host": "other.example.com"}, False),
            ("missing_key_matches_none", {"port": None}, False),
            ("key_named_like_a_lookup", {"contains": "x"}, False),
        ]
    )
    def test_exists_compares_config_keys_for_equality(self, _name: str, where: dict[str, Any], expected: bool) -> None:
        assert IntegrationManager.postgresql.credentials.exists(self.team.id, where=where) is expected

    def test_find_returns_the_oldest_row_and_list_can_reverse(self) -> None:
        newer = IntegrationManager.github.oauth.create(self.team.id, external_id="newer", config={})

        assert IntegrationManager.github.oauth.find(self.team.id) == self.rows["github_oauth"]
        assert IntegrationManager.github.oauth.list(self.team.id, newest_first=True)[0] == newer

    @parameterized.expand(
        [
            ("every_team", None, {"github_oauth": 2}),
            ("one_team", "other", {"github_oauth": 1}),
        ]
    )
    def test_list_by_external_id(self, _name: str, team_ids: str | None, expected: dict[str, int]) -> None:
        rows = IntegrationManager.github.oauth.list_by_external_id(
            "github_oauth", team_ids=[self.other_team.id] if team_ids else None
        )

        assert {"github_oauth": len(rows)} == expected
        assert all(row.integration_id == "github_oauth" for row in rows)

    @parameterized.expand(
        [
            ("both_teams", ["own", "other"], "github_oauth"),
            ("other_team_only", ["other"], "other"),
            ("empty", [], None),
            ("unknown_team", [10**9], None),
        ]
    )
    def test_find_and_exists_with_team_ids(self, _name: str, teams: list[Any], expected: str | None) -> None:
        by_name = {"own": self.team.id, "other": self.other_team.id}
        team_ids = [by_name.get(team, team) for team in teams]
        expected_row = {"github_oauth": self.rows["github_oauth"], "other": self.other_row}.get(expected or "")

        row = IntegrationManager.github.oauth.find(team_ids=team_ids, external_id="github_oauth")

        assert row == expected_row
        assert IntegrationManager.github.oauth.exists(team_ids=iter(team_ids)) is (expected_row is not None)
        assert async_to_sync(IntegrationManager.github.oauth.afind)(team_ids=team_ids) == expected_row
        assert async_to_sync(IntegrationManager.github.oauth.aexists)(team_ids=team_ids) is (expected_row is not None)

    @parameterized.expand(
        [
            ("neither", {}),
            ("both", {"team_id": 1, "team_ids": [1]}),
        ]
    )
    def test_find_and_exists_need_exactly_one_team_argument(self, _name: str, kwargs: dict[str, Any]) -> None:
        for read in (IntegrationManager.github.oauth.find, IntegrationManager.github.oauth.exists):
            with self.assertRaises(ValueError):
                read(**kwargs)

    @parameterized.expand(
        [
            ("own_row", "github_oauth", lambda self: self.rows["github_oauth"], True),
            ("row_of_another_team", "github_oauth", lambda self: self.other_row, True),
            ("row_with_another_external_id", "github_oauth", lambda self: self.rows["github_token"], False),
            ("another_workspace_id_for_the_external_id", "github_token", lambda self: self.other_row, False),
            ("missing_id", "github_oauth", lambda self: SimpleNamespace(id=10**9), False),
            ("not_a_number", "github_oauth", lambda self: SimpleNamespace(id="abc"), False),
        ]
    )
    def test_get_by_external_id(self, _name: str, external_id: str, row: Callable[[Any], Any], found: bool) -> None:
        expected = row(self)

        if found:
            assert IntegrationManager.github.oauth.get_by_external_id(external_id, expected.id) == expected
        else:
            with self.assertRaises(IntegrationNotFound):
                IntegrationManager.github.oauth.get_by_external_id(external_id, expected.id)

    @parameterized.expand(
        [
            ("every_team", lambda: IntegrationManager.github.oauth, "github_oauth", 2),
            ("other_auth_type_is_out_of_scope", lambda: IntegrationManager.github.oauth, "github_token", 0),
            ("kind_any", lambda: IntegrationManager.github.any, "github_token", 1),
            ("source_row_is_out_of_scope", lambda: IntegrationManager.stripe.any, "stripe_source", 0),
            ("missing", lambda: IntegrationManager.github.oauth, "missing", 0),
        ]
    )
    def test_count_and_exists_by_external_id(
        self, _name: str, accessor: Callable[[], IntegrationReader], external_id: str, expected: int
    ) -> None:
        assert accessor().count_by_external_id(external_id) == expected
        assert accessor().exists_by_external_id(external_id) is (expected > 0)

    @parameterized.expand(
        [
            ("get", lambda self, a: [a.get(self.team.id, self.rows["github_oauth"].id)]),
            ("get_many", lambda self, a: list(a.get_many(self.team.id, [self.rows["github_oauth"].id]).values())),
            ("find", lambda self, a: [a.find(self.team.id)]),
            ("list", lambda self, a: a.list(self.team.id)),
            ("list_by_external_id", lambda self, a: a.list_by_external_id("github_oauth")),
            ("get_by_external_id", lambda self, a: [a.get_by_external_id("github_oauth", self.other_row.id)]),
            ("update", lambda self, a: [a.update(self.team.id, self.rows["github_oauth"].id, errors="")]),
            ("upsert_of_an_existing_row", lambda self, a: [a.upsert(self.team.id, "github_oauth", config={})[0]]),
        ]
    )
    def test_reads_defer_the_repository_cache(
        self, _name: str, read: Callable[[Any, AuthAccessor], list[Integration]]
    ) -> None:
        Integration._base_manager.filter(integration_id="github_oauth").update(repository_cache=[{"name": "repo"}])

        rows = read(self, IntegrationManager.github.oauth)

        assert rows
        for row in rows:
            assert {"repository_cache", "repository_cache_updated_at"} <= row.get_deferred_fields()
            assert row.repository_cache == [{"name": "repo"}]

    def test_with_source_rows_refuses_a_source_only_accessor(self) -> None:
        with self.assertRaises(ValueError):
            IntegrationManager.source("stripe").any.with_source_rows()

    @parameterized.expand(
        [
            ("list_by_external_id", lambda: IntegrationManager.any.list_by_external_id("github_oauth")),
            ("delete_by_external_id", lambda: IntegrationManager.any.delete_by_external_id("github_oauth")),
            ("get_by_external_id", lambda: IntegrationManager.any.get_by_external_id("github_oauth", 1)),
            ("count_by_external_id", lambda: IntegrationManager.any.count_by_external_id("github_oauth")),
            ("exists_by_external_id", lambda: IntegrationManager.any.exists_by_external_id("github_oauth")),
        ]
    )
    def test_cross_team_operations_need_a_kind(self, _name: str, call: Callable[[], Any]) -> None:
        with self.assertRaises(ValueError):
            call()

        assert Integration._base_manager.filter(integration_id="github_oauth").count() == 2
        assert len(IntegrationManager.kinds("github").list_by_external_id("github_oauth")) == 2

    @parameterized.expand(
        [
            ("default_auth_type_stores_nothing", lambda: IntegrationManager.github.oauth, {}),
            ("non_default_auth_type_is_stored", lambda: IntegrationManager.github.token, {"auth_type": "token"}),
            (
                "token_on_a_credentials_kind",
                lambda: IntegrationManager.databricks.token,
                {"auth_type": "token"},
            ),
            ("credentials_default", lambda: IntegrationManager.databricks.credentials, {}),
            ("source_kind_default", lambda: IntegrationManager.source("ably").token, {MARKER: "Ably"}),
            (
                "source_row_of_a_catalogue_kind",
                lambda: IntegrationManager.source("stripe").token,
                {MARKER: "Stripe", "auth_type": "token"},
            ),
        ]
    )
    def test_create_stores_the_auth_type_only_when_it_is_not_the_default(
        self, _name: str, accessor: Callable[[], Any], expected_config: dict[str, Any]
    ) -> None:
        config = {MARKER: expected_config[MARKER]} if MARKER in expected_config else {}

        row = accessor().create(
            self.team.id, external_id="new", config=config, sensitive_config={"secret": "s"}, created_by_id=self.user.id
        )

        stored = Integration._base_manager.get(id=row.id)
        assert (stored.config, stored.sensitive_config, stored.created_by_id) == (
            expected_config,
            {"secret": "s"},
            self.user.id,
        )
        assert accessor().get(self.team.id, row.id) == row

    @parameterized.expand(
        [
            ("auth_type_in_config", lambda: IntegrationManager.github.token, {"auth_type": "token"}, ValueError),
            ("marker_through_named_accessor", lambda: IntegrationManager.stripe.token, {MARKER: "Stripe"}, ValueError),
            ("source_row_without_marker", lambda: IntegrationManager.source("ably").token, {}, ValueError),
            (
                "auth_type_the_kind_does_not_support",
                lambda: IntegrationManager.source("postgresql").token,
                {MARKER: "Postgres"},
                UnsupportedAuthType,
            ),
        ]
    )
    def test_create_rejects(
        self, _name: str, accessor: Callable[[], Any], config: dict[str, Any], error: type[Exception]
    ) -> None:
        with self.assertRaises(error):
            accessor().create(self.team.id, external_id="new", config=config)

    @parameterized.expand(
        [
            ("same_scope", lambda: IntegrationManager.github.oauth, "github_oauth", {}),
            ("other_auth_type", lambda: IntegrationManager.github.token, "github_oauth", {}),
            ("source_row_through_named_accessor", lambda: IntegrationManager.stripe.oauth, "stripe_source", {}),
            (
                "named_row_through_source_accessor",
                lambda: IntegrationManager.source("stripe").token,
                "stripe_token",
                {MARKER: "Stripe"},
            ),
        ]
    )
    def test_create_raises_conflict_on_the_unique_key(
        self, _name: str, accessor: Callable[[], Any], external_id: str, config: dict[str, Any]
    ) -> None:
        with self.assertRaises(IntegrationConflict):
            accessor().create(self.team.id, external_id=external_id, config=config)

        # The failed insert rolls back to a savepoint, so the transaction stays usable.
        assert IntegrationManager.any.with_source_rows().list(self.team.id, external_id=external_id) == [
            self.rows[external_id]
        ]

    def test_upsert_creates_then_replaces_the_config(self) -> None:
        row, created = IntegrationManager.github.token.upsert(self.team.id, "new", config={"a": 1})
        again, created_again = IntegrationManager.github.token.upsert(
            self.team.id, "new", config={"b": 2}, sensitive_config={"token": "t"}, created_by_id=self.user.id
        )

        again = Integration._base_manager.get(id=again.id)
        assert (created, created_again, again.id) == (True, False, row.id)
        assert (again.config, again.sensitive_config, again.created_by_id) == (
            {"b": 2, "auth_type": "token"},
            {"token": "t"},
            self.user.id,
        )

    @parameterized.expand(
        [
            ("other_auth_type", lambda: IntegrationManager.github.token, "github_oauth", {}),
            ("source_row", lambda: IntegrationManager.stripe.token, "stripe_source", {}),
            (
                "named_row_through_source",
                lambda: IntegrationManager.source("stripe").token,
                "stripe_token",
                {MARKER: "Stripe"},
            ),
        ]
    )
    def test_upsert_raises_on_a_row_out_of_scope(
        self, _name: str, accessor: Callable[[], Any], external_id: str, config: dict[str, Any]
    ) -> None:
        before = Integration._base_manager.get(id=self.rows[external_id].id).config

        with self.assertRaises(IntegrationConflict):
            accessor().upsert(self.team.id, external_id, config=config)

        assert Integration._base_manager.get(id=self.rows[external_id].id).config == before

    def test_update_merges_and_removes_keys(self) -> None:
        row = self.rows["github_token"]

        IntegrationManager.github.token.update(
            self.team.id,
            row.id,
            config_patch={"login": "octocat"},
            config_remove=["account", "missing"],
            sensitive_config_patch={"token": "t"},
            errors="TOKEN_REFRESH_FAILED",
        )

        stored = Integration._base_manager.get(id=row.id)
        assert (stored.config, stored.sensitive_config, stored.errors) == (
            {"auth_type": "token", "login": "octocat"},
            {"token": "t"},
            "TOKEN_REFRESH_FAILED",
        )

    @parameterized.expand(
        [
            ("patch_auth_type", {"config_patch": {"auth_type": "oauth"}}, ValueError),
            ("remove_auth_type", {"config_remove": ["auth_type"]}, ValueError),
            ("patch_marker", {"config_patch": {MARKER: "Stripe"}}, ValueError),
        ]
    )
    def test_update_rejects_reserved_keys(self, _name: str, kwargs: dict[str, Any], error: type[Exception]) -> None:
        with self.assertRaises(error):
            IntegrationManager.github.token.update(self.team.id, self.rows["github_token"].id, **kwargs)

    def test_upsert_without_created_by_keeps_the_creator(self) -> None:
        row = IntegrationManager.github.token.create(
            self.team.id, external_id="new", config={}, created_by_id=self.user.id
        )

        again, created = IntegrationManager.github.token.upsert(self.team.id, "new", config={"b": 2})

        assert (created, again.id) == (False, row.id)
        assert Integration._base_manager.get(id=row.id).created_by_id == self.user.id

    def test_upsert_updates_the_row_that_a_concurrent_insert_won(self) -> None:
        original_first = IntegrationQuerySet.first
        reads: list[int] = []

        def first_after_a_competing_insert(queryset: Any) -> Integration | None:
            result = original_first(queryset)
            reads.append(1)
            if len(reads) == 1:
                assert result is None
                Integration.objects._with_auth(ANY).create(
                    team=self.team, kind="github", integration_id="raced", config={"auth_type": "token", "old": True}
                )
            return result

        with patch.object(IntegrationQuerySet, "first", autospec=True, side_effect=first_after_a_competing_insert):
            row, created = IntegrationManager.github.token.upsert(
                self.team.id, "raced", config={"new": True}, created_by_id=self.user.id
            )

        stored = Integration._base_manager.filter(team=self.team, kind="github", integration_id="raced")
        saved = stored.get()
        assert (created, stored.count(), saved.id) == (False, 1, row.id)
        assert (saved.config, saved.created_by_id) == ({"new": True, "auth_type": "token"}, self.user.id)

    @parameterized.expand(
        [
            ("nothing", {}),
            ("empty_collections", {"config_patch": {}, "config_remove": (), "sensitive_config_patch": {}}),
        ]
    )
    def test_an_empty_patch_writes_nothing(self, _name: str, kwargs: dict[str, Any]) -> None:
        row = self.rows["github_oauth"]
        before = Integration._base_manager.get(id=row.id)

        with patch.object(Integration, "save") as save:
            updated = IntegrationManager.github.oauth.update(self.team.id, row.id, **kwargs)

        save.assert_not_called()
        assert (updated.config, updated.sensitive_config, updated.errors) == (
            before.config,
            before.sensitive_config,
            before.errors,
        )

    @parameterized.expand(
        [
            ("int_to_bool", 1, True),
            ("bool_to_int", True, 1),
            ("int_to_float", 1, 1.0),
            ("zero_to_false", 0, False),
            ("nested_int_to_bool", {"a": 1}, {"a": True}),
        ]
    )
    def test_update_writes_a_value_of_another_json_type(self, _name: str, stored: object, new: object) -> None:
        row = self.rows["github_oauth"]
        IntegrationManager.github.oauth.update(self.team.id, row.id, config_patch={"flag": stored})

        IntegrationManager.github.oauth.update(self.team.id, row.id, config_patch={"flag": new})

        saved = Integration._base_manager.get(id=row.id).config["flag"]
        assert (saved, type(saved)) == (new, type(new))

    @parameterized.expand(
        [
            ("auth_type_without_kinds", {"kinds": None, "auth_type": AuthType.TOKEN}),
            ("auth_type_with_empty_kinds", {"kinds": frozenset(), "auth_type": AuthType.TOKEN}),
        ]
    )
    def test_a_reader_with_an_auth_type_needs_kinds(self, _name: str, kwargs: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            IntegrationReader(**kwargs)

    def test_a_write_accessor_refuses_to_include_source_rows(self) -> None:
        with self.assertRaises(ValueError):
            AuthAccessor(kind="github", auth_type=AuthType.OAUTH, source_rows=SourceRows.INCLUDE)

    def test_update_raises_for_a_row_out_of_scope(self) -> None:
        with self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.update(self.team.id, self.rows["github_token"].id, errors="")

    def _resend_row(self, *, refreshed_ago: int) -> Integration:
        return Integration.objects._with_auth(ANY).create(
            team=self.team,
            kind="resend",
            integration_id="resend-account",
            config={"expires_in": 900, "refreshed_at": int(time.time()) - refreshed_ago},
            sensitive_config={"access_token": "old", "refresh_token": "r1"},
        )

    @parameterized.expand(
        [
            ("expired", 800, None, True),
            ("fresh", 10, None, False),
            ("fresh_but_the_caller_holds_the_stored_token", 10, "old", True),
            ("fresh_and_another_worker_rotated_the_token", 10, "older", False),
            ("expired_and_another_worker_rotated_the_token", 800, "older", True),
        ]
    )
    def test_refresh_access_token_refreshes_only_when_needed(
        self, _name: str, refreshed_ago: int, stale_access_token: str | None, refreshes: bool
    ) -> None:
        row = self._resend_row(refreshed_ago=refreshed_ago)

        def rotate(oauth: OauthIntegration) -> None:
            oauth.integration.sensitive_config = {"access_token": "new", "refresh_token": "r2"}
            oauth.integration.save()

        with (
            patch.object(OauthIntegration, "refresh_access_token", autospec=True, side_effect=rotate) as refresh,
            CaptureQueriesContext(connection) as queries,
        ):
            result = IntegrationManager.resend.oauth.refresh_access_token(
                self.team.id, row.id, stale_access_token=stale_access_token
            )

        expected_token = "new" if refreshes else "old"
        assert refresh.call_count == (1 if refreshes else 0)
        assert (result.id, result.sensitive_config["access_token"]) == (row.id, expected_token)
        assert Integration._base_manager.get(id=row.id).sensitive_config["access_token"] == expected_token
        assert any("FOR UPDATE" in query["sql"] for query in queries.captured_queries)

    @parameterized.expand(
        [
            ("kind_without_a_refresh", lambda: IntegrationManager.github.oauth, "github_oauth", ValueError),
            ("row_of_another_kind", lambda: IntegrationManager.stripe.oauth, "github_oauth", IntegrationNotFound),
            (
                "row_with_another_auth_type",
                lambda: IntegrationManager.stripe.oauth,
                "stripe_token",
                IntegrationNotFound,
            ),
        ]
    )
    def test_refresh_access_token_raises(
        self, _name: str, accessor: Callable[[], Any], row_name: str, error: type[Exception]
    ) -> None:
        with patch.object(OauthIntegration, "refresh_access_token") as refresh:
            with self.assertRaises(error):
                accessor().refresh_access_token(self.team.id, self.rows[row_name].id)

        refresh.assert_not_called()

    @parameterized.expand(
        [
            # Queries: the savepoint, the locked read, the one bulk update, the savepoint release.
            ("changes_every_team", [], IntegrationPatch(config_patch={"suspended": True}), 2, 4),
            ("skips_a_row_that_already_matches", ["other"], IntegrationPatch(config_patch={"suspended": True}), 1, 4),
            (
                "writes_nothing_when_nothing_changes",
                ["own", "other"],
                IntegrationPatch(config_patch={"suspended": True}),
                0,
                3,
            ),
            ("removes_a_key", ["own"], IntegrationPatch(config_remove=("suspended",)), 1, 4),
            ("errors_only", [], IntegrationPatch(errors="SUSPENDED"), 2, 4),
            ("empty_patch", [], IntegrationPatch(), 0, 3),
        ]
    )
    def test_update_by_external_id_reaches_every_team(
        self, _name: str, already_suspended: list[str], patch: IntegrationPatch, changed: int, queries: int
    ) -> None:
        by_name = {"own": self.rows["github_oauth"], "other": self.other_row}
        for name in already_suspended:
            Integration._base_manager.filter(id=by_name[name].id).update(config={"suspended": True})

        with self.assertNumQueries(queries):
            count = IntegrationManager.github.oauth.update_by_external_id("github_oauth", patch)

        stored = Integration._base_manager.filter(integration_id="github_oauth")
        assert count == changed
        if patch.config_patch:
            assert {row.config.get("suspended") for row in stored} == {True}
        if patch.config_remove:
            assert {row.config.get("suspended") for row in stored} == {None}
        if patch.errors:
            assert {row.errors for row in stored} == {"SUSPENDED"}
        assert "suspended" not in Integration._base_manager.get(id=self.rows["github_token"].id).config

    def test_update_by_external_id_rejects_reserved_keys(self) -> None:
        with self.assertRaises(ValueError):
            IntegrationManager.github.oauth.update_by_external_id(
                "github_oauth", IntegrationPatch(config_patch={MARKER: "Github"})
            )

    def test_delete_checks_usages(self) -> None:
        row = self.rows["github_oauth"]

        def provider(team_id: int, integration_id: int) -> list[IntegrationUsage]:
            return [IntegrationUsage(type="workflow", id="1", name="Flow")] if integration_id == row.id else []

        with _usage_providers(provider):
            with self.assertRaises(IntegrationInUse) as raised:
                IntegrationManager.github.oauth.delete(self.team.id, row.id)
            assert raised.exception.usages == [IntegrationUsage(type="workflow", id="1", name="Flow")]

            IntegrationManager.github.oauth.delete(self.team.id, row.id, ignore_usages=True)
            IntegrationManager.github.token.delete(self.team.id, self.rows["github_token"].id)

        assert not Integration._base_manager.filter(id__in=[row.id, self.rows["github_token"].id]).exists()

    def test_delete_raises_for_a_row_out_of_scope(self) -> None:
        with _usage_providers(), self.assertRaises(IntegrationNotFound):
            IntegrationManager.github.oauth.delete(self.team.id, self.rows["github_token"].id)

    def test_delete_by_external_id_reaches_every_team(self) -> None:
        assert IntegrationManager.github.oauth.delete_by_external_id("github_oauth") == 2
        assert not Integration._base_manager.filter(integration_id="github_oauth").exists()
        assert Integration._base_manager.filter(id=self.rows["github_token"].id).exists()

    def test_delete_by_external_id_rolls_back_every_row_when_one_delete_fails(self) -> None:
        original_delete = Integration.delete
        calls: list[int] = []

        def delete_then_fail_on_the_second_row(row: Integration, *args: Any, **kwargs: Any) -> Any:
            calls.append(row.id)
            if len(calls) == 2:
                raise RuntimeError("delete failed")
            return original_delete(row, *args, **kwargs)

        with patch.object(Integration, "delete", autospec=True, side_effect=delete_then_fail_on_the_second_row):
            with self.assertRaises(RuntimeError):
                IntegrationManager.github.oauth.delete_by_external_id("github_oauth")

        assert len(calls) == 2
        assert Integration._base_manager.filter(integration_id="github_oauth").count() == 2

    def test_usages_reads_registered_and_product_providers_in_order(self) -> None:
        row = self.rows["postgres"]
        product_module = SimpleNamespace(
            integration_usages=lambda team_id, integration_id: [
                IntegrationUsage(type="warehouse_source", id="2", name="b"),
                IntegrationUsage(type="warehouse_source", id="1", name="a"),
            ]
        )

        with (
            patch.object(usages, "_registered", []),
            patch.object(usages, "_product_providers", None),
            patch.object(usages, "load_product_modules", return_value=iter([product_module])) as load,
        ):
            register_usage_provider(
                lambda team_id, integration_id: [IntegrationUsage(type="batch_export", id="9", name="z")]
            )
            first = IntegrationManager.postgresql.credentials.usages(self.team.id, row.id)
            IntegrationManager.postgresql.credentials.usages(self.team.id, row.id)

        assert [(usage.type, usage.name) for usage in first] == [
            ("batch_export", "z"),
            ("warehouse_source", "a"),
            ("warehouse_source", "b"),
        ]
        load.assert_called_once_with("integration_usages")

    def test_a_provider_module_that_registers_at_import_does_not_deadlock(self) -> None:
        def import_a_module_that_registers(_name: str) -> Iterable[SimpleNamespace]:
            register_usage_provider(lambda team_id, integration_id: [])
            return [SimpleNamespace(integration_usages=lambda team_id, integration_id: [])]

        with (
            patch.object(usages, "_registered", []),
            patch.object(usages, "_product_providers", None),
            patch.object(usages, "load_product_modules", side_effect=import_a_module_that_registers),
        ):
            # A daemon thread, so a deadlock fails the test instead of hanging the run.
            loader = threading.Thread(target=usages.integration_usages, args=(self.team.id, 1), daemon=True)
            loader.start()
            loader.join(timeout=10)

            assert not loader.is_alive()
            assert len(usages._registered) == 1

    @parameterized.expand(
        [
            ("aget", lambda t, r: ("get", (t, r), {})),
            ("aget_many", lambda t, r: ("get_many", (t, [r]), {})),
            ("afind", lambda t, r: ("find", (t,), {"external_id": "github_oauth"})),
            ("alist", lambda t, r: ("list", (t,), {})),
            ("aexists", lambda t, r: ("exists", (t,), {"external_id": "github_oauth"})),
            ("ausages", lambda t, r: ("usages", (t, r), {})),
        ]
    )
    def test_async_reads_match_the_sync_reads(
        self, name: str, args: Callable[[int, int], tuple[str, tuple[Any, ...], dict[str, Any]]]
    ) -> None:
        accessor = IntegrationManager.github.oauth
        sync_name, call_args, call_kwargs = args(self.team.id, self.rows["github_oauth"].id)

        with _usage_providers(
            lambda team_id, integration_id: [IntegrationUsage(type="warehouse_source", id="1", name="a")]
        ):
            expected = getattr(accessor, sync_name)(*call_args, **call_kwargs)
            actual = async_to_sync(getattr(accessor, name))(*call_args, **call_kwargs)

        assert actual == expected
        assert actual not in (None, [], {}, False)

    def test_async_delete_deletes_and_honors_usages(self) -> None:
        accessor = IntegrationManager.github.oauth
        row = self.rows["github_oauth"]

        with _usage_providers(
            lambda team_id, integration_id: [IntegrationUsage(type="warehouse_source", id="1", name="a")]
        ):
            with self.assertRaises(IntegrationInUse):
                async_to_sync(accessor.adelete)(self.team.id, row.id)
            assert Integration._base_manager.filter(id=row.id).exists()
            async_to_sync(accessor.adelete)(self.team.id, row.id, ignore_usages=True)

        assert not Integration._base_manager.filter(id=row.id).exists()

    def test_async_writes_match_the_sync_writes(self) -> None:
        accessor = IntegrationManager.github.token
        row = self.rows["github_token"]

        created = async_to_sync(accessor.acreate)(
            self.team.id, external_id="made", config={"a": 1}, sensitive_config={"s": 1}, created_by_id=self.user.id
        )
        upserted, was_created = async_to_sync(accessor.aupsert)(self.team.id, "made", config={"b": 2})
        updated = async_to_sync(accessor.aupdate)(self.team.id, row.id, config_patch={"x": 1}, errors="boom")

        assert (created.config, created.sensitive_config, created.created_by_id) == (
            {"a": 1, "auth_type": "token"},
            {"s": 1},
            self.user.id,
        )
        assert (upserted.id, was_created, upserted.config) == (created.id, False, {"b": 2, "auth_type": "token"})
        assert (updated.config["x"], updated.errors) == (1, "boom")
        assert Integration._base_manager.get(id=row.id).config["x"] == 1

    def test_async_refresh_delegates_to_the_sync_refresh(self) -> None:
        # The async form runs in its own thread with its own connection, which cannot see the rows
        # of this test's transaction, so the sync refresh is replaced here.
        accessor = IntegrationManager.resend.oauth
        row = self._resend_row(refreshed_ago=800)

        with patch.object(OAuthAccessor, "refresh_access_token", autospec=True, return_value=row) as refresh:
            refreshed = async_to_sync(accessor.arefresh_access_token)(self.team.id, row.id, stale_access_token="old")

        assert refreshed is row
        refresh.assert_called_once_with(accessor, self.team.id, row.id, stale_access_token="old")


class TestRegistration(BaseTest):
    @parameterized.expand(
        [
            ("unknown_source_kind", lambda: IntegrationManager.source("acme-crm-unregistered")),
            ("unknown_kind", lambda: IntegrationManager.kinds("github", "acme-crm")),
            ("no_kinds", lambda: IntegrationManager.kinds()),
        ]
    )
    def test_unknown_kinds_raise(self, _name: str, build: Callable[[], Any]) -> None:
        with self.assertRaises(UnknownIntegrationKind):
            build()

    def test_register_source_kinds_sets_the_default_of_a_new_kind_only(self) -> None:
        with patch.dict(auth_types._KIND_AUTH_TYPES):
            register_source_kinds({"acme-sdk-test": AuthType.TOKEN, "stripe": AuthType.CREDENTIALS})

            assert default_auth_type("acme-sdk-test") == AuthType.TOKEN
            assert default_auth_type("stripe") == AuthType.OAUTH
            assert AuthType.CREDENTIALS in kind_auth_types("stripe").supported
            assert IntegrationManager.source("acme-sdk-test").token.list(self.team.id) == []

    def test_source_rows_of_a_catalogue_kind_use_the_warehouse_auth_type(self) -> None:
        row = IntegrationManager.source("clickup").credentials.create(
            self.team.id, external_id="new", config={MARKER: "ClickUp"}
        )

        assert default_auth_type("clickup") == AuthType.OAUTH
        assert row.config == {MARKER: "ClickUp", "auth_type": "credentials"}

    def test_register_source_kinds_rejects_a_changed_default(self) -> None:
        register_source_kinds({"acme-sdk-test-2": AuthType.TOKEN})

        with self.assertRaises(ValueError):
            register_source_kinds({"acme-sdk-test-2": AuthType.CREDENTIALS})

    def test_warehouse_sources_register_their_kinds_at_startup(self) -> None:
        assert IntegrationManager.source("ably").token is not None
        assert default_auth_type("ably") == AuthType.TOKEN
