from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection, transaction

from parameterized import parameterized

from posthog.integrations import IntegrationManager, IntegrationRecord, IntegrationUsage, lifecycle, usages
from posthog.integrations.contracts import IntegrationInUse, IntegrationNotFound
from posthog.models import Team
from posthog.models.integration import ANY, Integration

SavedCall = tuple[int, bool, bool]


@contextmanager
def _only_hooks(
    *, delete: tuple[lifecycle.DeleteHook, ...] = (), saved: tuple[lifecycle.SavedHook, ...] = ()
) -> Iterator[None]:
    with (
        patch.object(lifecycle, "_registered_delete", list(delete)),
        patch.object(lifecycle, "_registered_saved", list(saved)),
        patch.object(lifecycle, "_product_delete", []),
        patch.object(lifecycle, "_product_saved", []),
        patch.object(usages, "_registered", []),
        patch.object(usages, "_product_providers", []),
    ):
        yield


def _delete_one(team_id: int, row: Integration) -> None:
    IntegrationManager.github.oauth.delete(team_id, row.id)


def _delete_by_external_id(team_id: int, row: Integration) -> None:
    IntegrationManager.github.oauth.delete_by_external_id("installation-1")


class TestIntegrationLifecycleHooks(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.row = Integration.objects.create(
            team=self.team, kind="github", integration_id="installation-1", config={"a": 0}
        )

    def _row_exists(self) -> bool:
        return Integration._base_manager.filter(id=self.row.id).exists()

    @parameterized.expand([("delete", _delete_one, False), ("delete_by_external_id", _delete_by_external_id, True)])
    def test_delete_hooks_run_before_the_row_is_removed(
        self, _name: str, delete: Callable[[int, Integration], None], reaches_other_teams: bool
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_row = Integration.objects.create(team=other_team, kind="github", integration_id="installation-1")
        seen: list[tuple[int, int, bool, bool]] = []

        def hook(row: IntegrationRecord) -> None:
            exists = Integration._base_manager.filter(id=row.id).exists()
            seen.append((row.team_id, row.id, exists, lifecycle.sdk_runs_hooks()))

        with _only_hooks(delete=(hook,)):
            delete(self.team.id, self.row)

        expected = {(self.team.id, self.row.id, True, True)}
        if reaches_other_teams:
            expected.add((other_team.id, other_row.id, True, True))
        assert set(seen) == expected
        assert len(seen) == len(expected)
        assert not self._row_exists()
        assert not lifecycle.sdk_runs_hooks()

    @parameterized.expand([("delete", _delete_one), ("delete_by_external_id", _delete_by_external_id)])
    def test_a_failing_delete_hook_keeps_the_row_and_rolls_back_the_other_hooks(
        self, _name: str, delete: Callable[[int, Integration], None]
    ) -> None:
        def rename_team(row: IntegrationRecord) -> None:
            Team.objects.filter(id=row.team_id).update(name="Renamed by a hook")

        def fail(row: IntegrationRecord) -> None:
            raise RuntimeError("hook failed")

        with _only_hooks(delete=(rename_team, fail)), self.assertRaises(RuntimeError):
            delete(self.team.id, self.row)

        assert self._row_exists()
        assert Team.objects.get(id=self.team.id).name != "Renamed by a hook"

    @parameterized.expand(
        [
            ("in_use", lambda test: test.row.id, IntegrationInUse),
            ("out_of_scope", lambda test: test.token_row.id, IntegrationNotFound),
            ("other_team", lambda test: test.other_team_row.id, IntegrationNotFound),
        ]
    )
    def test_delete_hooks_do_not_run_when_the_delete_is_refused(
        self, _name: str, row_id: Callable[["TestIntegrationLifecycleHooks"], int], error: type[Exception]
    ) -> None:
        self.token_row = Integration.objects._with_auth(ANY).create(
            team=self.team, kind="github", integration_id="token-row", config={"auth_type": "token"}
        )
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self.other_team_row = Integration.objects.create(team=other_team, kind="github", integration_id="o")
        calls: list[int] = []

        with _only_hooks(delete=(lambda row: calls.append(row.id),)):
            with patch.object(
                usages,
                "_product_providers",
                [lambda team_id, integration_id: [IntegrationUsage(type="workflow", id="1", name="Flow")]],
            ):
                with self.assertRaises(error):
                    IntegrationManager.github.oauth.delete(self.team.id, row_id(self))

        assert calls == []

    @parameterized.expand(
        [
            (
                "create",
                lambda team_id, row: IntegrationManager.github.oauth.create(
                    team_id, external_id="new", config={"a": 1}
                ),
                True,
                True,
            ),
            (
                "upsert_new_row",
                lambda team_id, row: IntegrationManager.github.oauth.upsert(team_id, "new", config={"a": 1})[0],
                True,
                True,
            ),
            (
                "upsert_existing_row",
                lambda team_id, row: IntegrationManager.github.oauth.upsert(team_id, "installation-1", config={})[0],
                False,
                True,
            ),
            (
                "update_config",
                lambda team_id, row: IntegrationManager.github.oauth.update(team_id, row.id, config_patch={"a": 1}),
                False,
                True,
            ),
            (
                "update_config_remove",
                lambda team_id, row: IntegrationManager.github.oauth.update(team_id, row.id, config_remove=["a"]),
                False,
                True,
            ),
            (
                "update_errors_only",
                lambda team_id, row: IntegrationManager.github.oauth.update(team_id, row.id, errors="boom"),
                False,
                False,
            ),
            (
                "update_secret_only",
                lambda team_id, row: IntegrationManager.github.oauth.update(
                    team_id, row.id, sensitive_config_patch={"access_token": "new"}
                ),
                False,
                False,
            ),
        ]
    )
    def test_saved_hooks_get_the_row_and_what_changed(
        self,
        _name: str,
        write: Callable[[int, Integration], IntegrationRecord],
        created: bool,
        config_changed: bool,
    ) -> None:
        calls: list[SavedCall] = []
        flags_during_write: list[bool] = []

        def hook(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
            calls.append((row.id, created, config_changed))

        with (
            _only_hooks(saved=(hook,)),
            patch.object(Integration, "save", autospec=True, side_effect=_recording_save(flags_during_write)),
        ):
            written = write(self.team.id, self.row)

        assert calls == [(written.id, created, config_changed)]
        assert flags_during_write and all(flags_during_write)

    def test_a_failing_saved_hook_is_logged_and_the_write_stays(self) -> None:
        later: list[int] = []

        def fail(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
            raise RuntimeError("hook failed")

        def record(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
            later.append(row.id)

        with _only_hooks(saved=(fail, record)), patch.object(lifecycle, "capture_exception") as capture:
            row = IntegrationManager.github.oauth.create(self.team.id, external_id="new", config={})

        assert Integration._base_manager.filter(id=row.id).exists()
        assert later == [row.id]
        capture.assert_called_once()

    def test_a_database_error_in_a_saved_hook_leaves_the_caller_transaction_usable(self) -> None:
        def fail_in_the_database(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 / 0")

        with _only_hooks(saved=(fail_in_the_database,)), patch.object(lifecycle, "capture_exception") as capture:
            with transaction.atomic():
                row = IntegrationManager.github.oauth.create(self.team.id, external_id="new", config={})
                assert Integration._base_manager.filter(id=row.id).exists()

        capture.assert_called_once()

    @parameterized.expand(
        [
            ("both", {"before_integration_delete": "d", "after_integration_saved": "s"}, ["d"], ["s"]),
            ("delete_only", {"before_integration_delete": "d"}, ["d"], []),
            ("saved_only", {"after_integration_saved": "s"}, [], ["s"]),
            ("neither", {}, [], []),
        ]
    )
    def test_product_hook_modules_are_loaded_once(
        self, _name: str, functions: dict[str, str], delete: list[str], saved: list[str]
    ) -> None:
        module = SimpleNamespace(**functions)

        with (
            patch.object(lifecycle, "_registered_delete", ["registered"]),
            patch.object(lifecycle, "_registered_saved", []),
            patch.object(lifecycle, "_product_delete", None),
            patch.object(lifecycle, "_product_saved", None),
            patch.object(lifecycle, "load_product_modules", return_value=iter([module])) as load,
        ):
            loaded_delete: list[object] = list(lifecycle.delete_hooks())
            loaded_saved: list[object] = list(lifecycle.saved_hooks())
            assert loaded_delete == [*delete, "registered"]
            assert loaded_saved == saved

        load.assert_called_once_with("integration_hooks")

    def test_register_ignores_a_hook_that_is_already_registered(self) -> None:
        def hook(row: IntegrationRecord) -> None: ...

        with _only_hooks():
            lifecycle.register_delete_hook(hook)
            lifecycle.register_delete_hook(hook)

            assert lifecycle.delete_hooks() == [hook]


def _recording_save(flags: list[bool]) -> Callable[..., None]:
    original_save = Integration.save

    def save(row: Integration, *args: Any, **kwargs: Any) -> None:
        flags.append(lifecycle.sdk_runs_hooks())
        original_save(row, *args, **kwargs)

    return save
