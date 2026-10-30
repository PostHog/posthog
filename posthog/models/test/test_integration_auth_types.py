from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest

from django.db import models
from django.db.migrations.state import ModelState
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.integrations.catalogue import KINDS
from posthog.models import Team, User
from posthog.models.integration import ANY, DEFAULT, AuthRequirement, Integration, IntegrationAuthType
from posthog.models.integration.auth_types import config_for_write

AuthType = IntegrationAuthType


class TestIntegrationAuthTypeCatalogue(SimpleTestCase):
    def test_every_integration_kind_has_a_catalogue_entry(self) -> None:
        assert set(KINDS) == set(Integration.IntegrationKind.values)

    @parameterized.expand(
        [
            ("nothing", ()),
            ("any_with_a_type", (ANY, AuthType.OAUTH)),
            ("any_with_default", (ANY, DEFAULT)),
            ("unknown_string", ("bogus",)),
        ]
    )
    def test_requirement_rejects_invalid_selectors(self, _name: str, selectors: tuple[Any, ...]) -> None:
        with self.assertRaises(ValueError):
            AuthRequirement.of(*selectors)

    @parameterized.expand(
        [
            ("non_default_type_is_written", "github", {}, (AuthType.TOKEN,), {"auth_type": "token"}),
            ("plain_string_type_is_written", "github", {"a": 1}, ("token",), {"a": 1, "auth_type": "token"}),
            ("missing_config_gets_the_type", "slack", None, (AuthType.TOKEN,), {"auth_type": "token"}),
            ("token_on_a_credentials_kind_is_written", "databricks", {}, (AuthType.TOKEN,), {"auth_type": "token"}),
            ("default_type_is_not_written", "github", {}, (AuthType.OAUTH,), {}),
            ("stored_type_in_requirement_is_kept", "github", {"auth_type": "token"}, (AuthType.TOKEN,), None),
            ("several_types_with_the_default", "github", {}, (AuthType.OAUTH, AuthType.TOKEN), {}),
            ("default_selector", "github", {}, (DEFAULT,), {}),
            ("any_keeps_config", "github", {"a": 1}, (ANY,), {"a": 1}),
            ("any_keeps_stored_type", "github", {"auth_type": "token"}, (ANY,), None),
            ("unknown_kind_default", "acme-crm", {}, (AuthType.CREDENTIALS,), {}),
        ]
    )
    def test_config_for_write(
        self,
        _name: str,
        kind: str | None,
        config: dict | None,
        selectors: tuple[Any, ...],
        expected: dict | None,
    ) -> None:
        result = config_for_write(kind, config, AuthRequirement.of(*selectors))

        assert result == (config if expected is None else expected)

    @parameterized.expand(
        [
            ("type_the_kind_does_not_support", "postgresql", {}, (AuthType.TOKEN,)),
            ("stored_type_the_kind_does_not_support", "postgresql", {"auth_type": "token"}, (ANY,)),
            ("stored_type_outside_requirement", "github", {"auth_type": "token"}, (AuthType.OAUTH,)),
            ("several_types_without_the_default", "github", {}, (AuthType.TOKEN, AuthType.CREDENTIALS)),
            ("unknown_kind_with_a_specific_type", "acme-crm", {}, (AuthType.TOKEN,)),
            # Every auth type is the default of some kind, so a write without the kind cannot tell.
            ("no_kind_with_oauth", None, {}, (AuthType.OAUTH,)),
            ("no_kind_with_token", None, {}, (AuthType.TOKEN,)),
        ]
    )
    def test_config_for_write_rejects(
        self, _name: str, kind: str | None, config: dict, selectors: tuple[Any, ...]
    ) -> None:
        with self.assertRaises(ValueError):
            config_for_write(kind, config, AuthRequirement.of(*selectors))

    @parameterized.expand(
        [
            ("missing_key", {}, None),
            ("stored_default", {"auth_type": "oauth"}, None),
            ("stored_non_default", {"auth_type": "token"}, ValueError),
        ]
    )
    def test_config_for_write_without_with_auth(
        self, _name: str, config: dict, expected_error: type[Exception] | None
    ) -> None:
        requirement = AuthRequirement.kind_default_only()

        if expected_error is None:
            assert config_for_write("github", config, requirement) == config
        else:
            with self.assertRaises(expected_error):
                config_for_write("github", config, requirement)


ROWS: dict[str, tuple[str, dict]] = {
    "github_oauth": ("github", {}),
    "github_oauth_explicit": ("github", {"auth_type": "oauth"}),
    "github_null": ("github", {"auth_type": None}),
    "github_token": ("github", {"auth_type": "token"}),
    "slack_oauth": ("slack", {}),
    "slack_token": ("slack", {"auth_type": "token"}),
    "postgres": ("postgresql", {}),
    "postgres_source": ("postgresql", {"warehouse_source_type": "Postgres"}),
    "unknown_kind": ("acme-crm", {}),
}
DEFAULT_ROWS = {
    "github_oauth",
    "github_oauth_explicit",
    "github_null",
    "slack_oauth",
    "postgres",
    "postgres_source",
    "unknown_kind",
}
# An unqualified query also skips warehouse source rows, whose config has another shape.
IMPLICIT_ROWS = DEFAULT_ROWS - {"postgres_source"}
GITHUB_OAUTH_ROWS = {"github_oauth", "github_oauth_explicit", "github_null"}


class TestIntegrationWithAuth(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.rows = {
            name: Integration.objects._with_auth(ANY).create(
                team=self.team, kind=kind, integration_id=name, config=config
            )
            for name, (kind, config) in ROWS.items()
        }

    def _names(self, queryset: models.QuerySet[Integration]) -> set[str]:
        return {row.integration_id for row in queryset.filter(team=self.team) if row.integration_id}

    @parameterized.expand(
        [
            ("oauth", lambda: Integration.objects._with_auth(AuthType.OAUTH), GITHUB_OAUTH_ROWS | {"slack_oauth"}),
            (
                "token_across_kinds",
                lambda: Integration.objects._with_auth(AuthType.TOKEN),
                {"github_token", "slack_token"},
            ),
            (
                "token_with_kind_in",
                lambda: Integration.objects._with_auth(AuthType.TOKEN).filter(kind__in=["slack", "postgresql"]),
                {"slack_token"},
            ),
            (
                "credentials_with_the_unknown_kind_default",
                lambda: Integration.objects._with_auth(AuthType.CREDENTIALS),
                {"postgres", "postgres_source", "unknown_kind"},
            ),
            (
                "oauth_with_kind",
                lambda: Integration.objects._with_auth(AuthType.OAUTH).filter(kind="github"),
                GITHUB_OAUTH_ROWS,
            ),
            ("default_selector", lambda: Integration.objects._with_auth(DEFAULT), DEFAULT_ROWS),
            ("default_and_token", lambda: Integration.objects._with_auth(DEFAULT, AuthType.TOKEN), set(ROWS)),
            ("any", lambda: Integration.objects._with_auth(ANY), set(ROWS)),
            ("unqualified_query", lambda: Integration.objects.all(), IMPLICIT_ROWS),
            ("unqualified_filter", lambda: Integration.objects.filter(kind="github"), GITHUB_OAUTH_ROWS),
            (
                "unqualified_filter_skips_source_rows",
                lambda: Integration.objects.filter(kind="postgresql"),
                {"postgres"},
            ),
            ("default_manager", lambda: Integration._default_manager.all(), set(ROWS)),
            (
                "narrowed_twice",
                lambda: Integration.objects._with_auth(ANY)._with_auth(AuthType.TOKEN),
                {"github_token", "slack_token"},
            ),
        ]
    )
    def test_with_auth_filters_rows(
        self, _name: str, queryset: Callable[[], models.QuerySet[Integration]], expected: set[str]
    ) -> None:
        assert self._names(queryset()) == expected

    def test_auth_type_property_reads_config_or_kind_default(self) -> None:
        assert {
            row.integration_id: row.auth_type for row in Integration.objects._with_auth(ANY).filter(team=self.team)
        } == {
            "github_oauth": "oauth",
            "github_oauth_explicit": "oauth",
            "github_null": "oauth",
            "github_token": "token",
            "slack_oauth": "oauth",
            "slack_token": "token",
            "postgres": "credentials",
            "postgres_source": "credentials",
            "unknown_kind": "credentials",
        }

    def test_save_drops_a_stored_auth_type_that_is_null_or_the_kind_default(self) -> None:
        token_row = self.rows["github_token"]
        token_row.config = {"auth_type": "oauth", "a": 1}
        token_row.save()

        stored = {
            row.integration_id: row.config
            for row in Integration._base_manager.filter(
                team=self.team,
                integration_id__in=["github_oauth_explicit", "github_null", "github_token", "slack_token"],
            )
        }
        assert stored == {
            "github_oauth_explicit": {},
            "github_null": {},
            "github_token": {"a": 1},
            "slack_token": {"auth_type": "token"},
        }

    def test_unqualified_queries_do_not_touch_non_default_rows(self) -> None:
        updated = Integration.objects.filter(team=self.team, kind="github").update(errors="x")
        deleted, _ = Integration.objects.filter(team=self.team, kind="slack").delete()

        assert (updated, deleted) == (3, 1)
        assert Integration.objects._with_auth(AuthType.TOKEN).filter(team=self.team).count() == 2

    @parameterized.expand(
        [
            ("create", lambda qs, **kw: qs.create(**kw)),
            ("get_or_create", lambda qs, **kw: qs.get_or_create(**kw)[0]),
            ("update_or_create", lambda qs, **kw: qs.update_or_create(**kw)[0]),
            ("bulk_create", lambda qs, **kw: qs.bulk_create([Integration(**kw)])[0]),
        ]
    )
    def test_writes_through_one_non_default_type_store_it(self, _name: str, write: Callable[..., Integration]) -> None:
        row = write(Integration.objects._with_auth(AuthType.TOKEN), team=self.team, kind="github", integration_id="new")

        assert Integration._base_manager.get(team=self.team, integration_id="new").config == {"auth_type": "token"}
        assert row.auth_type == "token"
        assert not Integration.objects.filter(team=self.team, integration_id="new").exists()

    @parameterized.expand([("create",), ("get_or_create",), ("update_or_create",)])
    def test_writes_through_the_default_type_store_nothing(self, method: str) -> None:
        getattr(Integration.objects._with_auth(AuthType.OAUTH), method)(
            team=self.team, kind="github", integration_id="new"
        )

        row = Integration.objects.get(team=self.team, integration_id="new")
        assert (row.config, row.auth_type) == ({}, "oauth")

    def test_update_or_create_keeps_the_auth_type_of_an_existing_row(self) -> None:
        row, created = Integration.objects._with_auth(AuthType.TOKEN).update_or_create(
            team=self.team, kind="github", integration_id="github_token", defaults={"config": {"account": "a"}}
        )

        row.refresh_from_db()
        assert (created, row.config) == (False, {"account": "a", "auth_type": "token"})

    def test_unqualified_create_rejects_a_non_default_type(self) -> None:
        with self.assertRaises(ValueError):
            Integration.objects.create(
                team=self.team, kind="github", integration_id="new", config={"auth_type": "token"}
            )

    @parameterized.expand(
        [
            ("all", lambda: Integration.objects.all()._with_auth(ANY)),  # type: ignore[attr-defined]
            ("filter", lambda: Integration.objects.filter(kind="github")._with_auth(AuthType.TOKEN)),
            (
                "chained_auth_types",
                lambda: Integration.objects._with_auth(AuthType.OAUTH)._with_auth(AuthType.TOKEN),
            ),
        ]
    )
    def test_with_auth_after_an_unqualified_query_raises(self, _name: str, build: Callable[[], Any]) -> None:
        with self.assertRaises(ValueError):
            build()

    def test_related_and_base_managers_are_not_filtered(self) -> None:
        token_row = self.rows["github_token"]
        prefetched_team = Team.objects.prefetch_related("integration_set").get(pk=self.team.pk)

        token_row.refresh_from_db()
        assert {row.integration_id for row in self.team.integration_set.all()} == set(ROWS)
        assert {row.integration_id for row in prefetched_team.integration_set.all()} == set(ROWS)
        assert self._names(Integration._base_manager.all()) == set(ROWS)
        assert self._names(self.team.integration_set._with_auth(AuthType.TOKEN)) == {"github_token", "slack_token"}

    def test_the_unfiltered_default_manager_does_not_change_the_migration_state(self) -> None:
        # A default manager that is not named `objects` would need a migration.
        assert (Integration._default_manager.name, ModelState.from_model(Integration).managers) == ("objects", [])
        assert Integration.objects is not Integration._default_manager
        assert self._names(Integration._default_manager._with_auth(AuthType.TOKEN)) == {"github_token", "slack_token"}

    def test_deleting_the_creator_reaches_non_default_rows(self) -> None:
        creator = User.objects.create_and_join(self.organization, "creator@example.com", None)
        Integration._base_manager.filter(team=self.team).update(created_by=creator)

        creator.delete()

        assert not Integration._base_manager.filter(team=self.team, created_by__isnull=False).exists()
