from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import UUID

from posthog.test.base import NonAtomicBaseTest

from django.db import DatabaseError, close_old_connections, connection, transaction

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.file_system.file_system import FileSystem, create_or_update_file
from posthog.test.waiting import wait_until


class TestFileSystemWritesUnderRealTransactions(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.client.force_login(self.user)

    def _blocked_backends(self) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0"
            )
            return cursor.fetchone()[0]

    def _wait_for_blocked_backends(self, count: int) -> None:
        wait_until(lambda: self._blocked_backends() >= count, timeout=10, message=f"expected {count} blocked backends")

    def test_a_folder_move_and_a_file_sync_of_the_same_object_both_finish(self) -> None:
        dashboard_id = str(
            self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Report"}).json()["id"]
        )
        FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        rows = sorted(
            (
                FileSystem.objects.create(team=self.team, path="Inbox/x", depth=2, type="dashboard", ref=dashboard_id)
                for _ in range(3)
            ),
            key=lambda row: row.id,
        )
        for row, path in zip(rows, ["Inbox/c", "Inbox/b", "Inbox/a"]):
            FileSystem.objects.filter(pk=row.pk).update(path=path)
        middle_locked = Event()
        release_middle = Event()

        def hold_the_middle_row() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_filesystem WHERE id = %s FOR UPDATE", [rows[1].id])
                    middle_locked.set()
                    release_middle.wait(timeout=10)
            finally:
                close_old_connections()

        def sync_the_files() -> None:
            close_old_connections()
            try:
                with transaction.atomic():
                    create_or_update_file(
                        team=self.team,
                        base_folder="Unfiled/Dashboards",
                        name="Report v2",
                        file_type="dashboard",
                        ref=dashboard_id,
                        href=f"/dashboard/{dashboard_id}",
                        meta={},
                    )
            finally:
                close_old_connections()

        def move_the_folder() -> Any:
            close_old_connections()
            try:
                return self.client.post(
                    f"/api/projects/{self.team.id}/file_system/{folder.id}/move/",
                    {"new_path": "Archive/Inbox"},
                    format="json",
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            holder = executor.submit(hold_the_middle_row)
            self.assertTrue(middle_locked.wait(timeout=5))
            try:
                sync = executor.submit(sync_the_files)
                self._wait_for_blocked_backends(1)
                move = executor.submit(move_the_folder)
                self._wait_for_blocked_backends(2)
            finally:
                release_middle.set()
            holder.result(timeout=15)
            sync.result(timeout=15)
            moved = move.result(timeout=15)

        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertEqual(
            sorted(
                FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).values_list(
                    "path", flat=True
                )
            ),
            ["Archive/Inbox/Report v2"] * 3,
        )

    def test_a_folder_move_leaves_its_team_free_for_new_rows(self) -> None:
        folder = FileSystem.objects.create(team=self.team, path="Inbox", depth=1, type="folder")
        FileSystem.objects.create(team=self.team, path="Inbox/Reports", depth=2, type="folder")
        outcomes: list[str] = []

        def file_a_row_in_the_same_team() -> str:
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '500ms'")
                    FileSystem.objects.create(team=self.team, path="Other", depth=1, type="folder")
                return "filed"
            except DatabaseError:
                return "blocked"
            finally:
                close_old_connections()

        def file_during_the_move(execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]) -> Any:
            result = execute(sql, params, many, context)
            if not outcomes and sql.startswith('UPDATE "posthog_filesystem"'):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    outcomes.append(executor.submit(file_a_row_in_the_same_team).result(timeout=10))
            return result

        with connection.execute_wrapper(file_during_the_move):
            moved = self.client.post(
                f"/api/projects/{self.team.id}/file_system/{folder.id}/move/",
                {"new_path": "Archive/Inbox"},
                format="json",
            )

        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertEqual(outcomes, ["filed"])

    def test_two_deletes_of_files_for_the_same_object_both_finish(self) -> None:
        dashboard_id = str(
            self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Report"}).json()["id"]
        )
        FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()
        first, second = sorted(
            (
                FileSystem.objects.create(
                    team=self.team, path=path, depth=1, type="dashboard", ref=dashboard_id, shortcut=False
                )
                for path in ["Report", "Report copy"]
            ),
            key=lambda row: row.id,
        )
        first_locked = Event()
        release_first = Event()

        def hold_the_first_row() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_filesystem WHERE id = %s FOR UPDATE", [first.id])
                    first_locked.set()
                    release_first.wait(timeout=10)
            finally:
                close_old_connections()

        def delete(row: FileSystem) -> Any:
            close_old_connections()
            try:
                return self.client.delete(f"/api/projects/{self.team.id}/file_system/{row.id}/")
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            holder = executor.submit(hold_the_first_row)
            self.assertTrue(first_locked.wait(timeout=5))
            try:
                deleting_first = executor.submit(delete, first)
                self._wait_for_blocked_backends(1)
                deleting_second = executor.submit(delete, second)
                self._wait_for_blocked_backends(2)
            finally:
                release_first.set()
            holder.result(timeout=15)
            statuses = sorted(
                [deleting_first.result(timeout=15).status_code, deleting_second.result(timeout=15).status_code]
            )

        self.assertEqual(statuses, [200, 204])
        self.assertFalse(FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).exists())

    @parameterized.expand([("move_and_folder_delete",), ("parent_and_child_folder_delete",)])
    def test_two_folder_writes_that_share_rows_both_finish(self, scenario: str) -> None:
        dashboard_ids = sorted(
            (
                str(self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": name}).json()["id"])
                for name in ["X", "Y", "Z"]
            ),
        )
        for dashboard_id in dashboard_ids:
            FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()
        first_ref, middle_ref, last_ref = dashboard_ids

        def file_row(path: str, ref: str) -> FileSystem:
            return FileSystem.objects.create(
                team=self.team, path=path, depth=path.count("/") + 1, type="dashboard", ref=ref, shortcut=False
            )

        first: tuple[str, str, dict[str, str] | None]
        second: tuple[str, str, dict[str, str] | None]
        if scenario == "move_and_folder_delete":
            moved = FileSystem.objects.create(team=self.team, path="Move", depth=1, type="folder")
            low, middle, high = sorted((file_row(f"Move/{n}", first_ref) for n in "abc"), key=lambda row: row.id)
            for row, ref in [(low, last_ref), (middle, middle_ref), (high, first_ref)]:
                FileSystem.objects.filter(pk=row.pk).update(ref=ref)
            deleted = FileSystem.objects.create(team=self.team, path="Delete", depth=1, type="folder")
            for ref in dashboard_ids:
                file_row(f"Delete/{ref}", ref)
            held = middle
            first = ("post", f"{moved.id}/move/", {"new_path": "Archive/Move"})
            second = ("delete", f"{deleted.id}/?recursive=true", None)
        else:
            parent = FileSystem.objects.create(team=self.team, path="Parent", depth=1, type="folder")
            child = FileSystem.objects.create(team=self.team, path="Parent/Child", depth=2, type="folder")
            held = file_row("Parent/Child/Report", first_ref)
            first = ("delete", f"{parent.id}/?recursive=true", None)
            second = ("delete", f"{child.id}/?recursive=true", None)
        held_locked = Event()
        release_held = Event()

        def hold_the_shared_row() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute("SELECT id FROM posthog_filesystem WHERE id = %s FOR UPDATE", [held.id])
                    held_locked.set()
                    release_held.wait(timeout=10)
            finally:
                close_old_connections()

        def send(request: tuple[str, str, dict | None]) -> Any:
            close_old_connections()
            try:
                method, suffix, payload = request
                return getattr(self.client, method)(
                    f"/api/projects/{self.team.id}/file_system/{suffix}", payload, format="json"
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            holder = executor.submit(hold_the_shared_row)
            self.assertTrue(held_locked.wait(timeout=5))
            try:
                sending_first = executor.submit(send, first)
                self._wait_for_blocked_backends(1)
                sending_second = executor.submit(send, second)
                self._wait_for_blocked_backends(2)
            finally:
                release_held.set()
            holder.result(timeout=15)
            statuses = [sending_first.result(timeout=15).status_code, sending_second.result(timeout=15).status_code]

        if scenario == "move_and_folder_delete":
            self.assertEqual(statuses, [200, 204])
            self.assertEqual(
                sorted(FileSystem.objects.filter(team=self.team, type="dashboard").values_list("path", flat=True)),
                ["Archive/Move/a", "Archive/Move/b", "Archive/Move/c"],
            )
        else:
            self.assertEqual(statuses, [200, 404])
            self.assertFalse(FileSystem.objects.filter(team=self.team, path__startswith="Parent").exists())

    def test_a_delete_that_finds_a_new_surface_after_its_lock_relocks_in_id_order(self) -> None:
        dashboard_id = str(
            self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Shared"}).json()["id"]
        )
        FileSystem.objects.filter(team=self.team, type="dashboard", ref=dashboard_id).delete()

        def file_row(path: str, **fields: Any) -> FileSystem:
            return FileSystem.objects.create(
                team=self.team, path=path, depth=1, type="dashboard", ref=dashboard_id, shortcut=False, **fields
            )

        target = file_row("Target")
        sibling = file_row("Sibling")
        early_id = UUID(int=1)
        other_holds_both = Event()

        def commit_the_early_row_on_a_new_surface() -> None:
            close_old_connections()
            try:
                file_row("Early", id=early_id, surface="synthetic-surface")
            finally:
                close_old_connections()

        def lock_the_early_row_then_the_sibling() -> None:
            close_old_connections()
            try:
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM posthog_filesystem WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                        [[early_id, sibling.id]],
                    )
                    other_holds_both.set()
            finally:
                close_old_connections()

        def wait_for_one_blocked_backend() -> None:
            close_old_connections()
            try:
                self._wait_for_blocked_backends(1)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures: list[Any] = []

            def interleave_after_the_first_lock(
                execute: Any, sql: str, params: Any, many: bool, context: dict[str, Any]
            ) -> Any:
                result = execute(sql, params, many, context)
                if not futures and sql.startswith("SELECT") and "FOR UPDATE" in sql and "posthog_filesystem" in sql:
                    executor.submit(commit_the_early_row_on_a_new_surface).result(timeout=10)
                    futures.append(executor.submit(lock_the_early_row_then_the_sibling))
                    executor.submit(wait_for_one_blocked_backend).result(timeout=15)
                return result

            def delete_the_target() -> Any:
                close_old_connections()
                try:
                    with connection.execute_wrapper(interleave_after_the_first_lock):
                        return self.client.delete(f"/api/projects/{self.team.id}/file_system/{target.id}/")
                finally:
                    close_old_connections()

            response = executor.submit(delete_the_target).result(timeout=30)
            self.assertEqual(len(futures), 1)
            futures[0].result(timeout=15)

        self.assertEqual(response.status_code, 204, response.content)
        self.assertTrue(other_holds_both.is_set())
        self.assertFalse(FileSystem.objects.filter(pk=target.pk).exists())
        self.assertEqual(
            sorted(FileSystem.objects.filter(team=self.team, ref=dashboard_id).values_list("path", flat=True)),
            ["Early", "Sibling"],
        )
