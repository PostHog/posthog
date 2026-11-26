from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, DatabaseError, close_old_connections, connection, router, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models import Tag, TaggedItem, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.tag import tag_assignment_transaction
from posthog.tag_management import (
    TagMergeResult,
    delete_unused_tag,
    delete_unused_tags,
    get_merge_preview,
    merge_tags,
    rename_tag,
)
from posthog.test.waiting import wait_until

from products.customer_analytics.backend.models import Account
from products.dashboards.backend.models.dashboard import Dashboard
from products.event_definitions.backend.models import EventDefinition, PropertyDefinition
from products.notebooks.backend.logic import set_notebook_tags
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight


class TestTagManagement(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = Tag.objects.create(team=self.team, name="customers")
        self.target = Tag.objects.create(team=self.team, name="customer")

    def test_merge_preserves_typed_assignments_and_deduplicates_overlap(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard", deleted=True)
        insight = Insight.objects.create(team=self.team, id=dashboard.id)
        event = EventDefinition.objects.create(team=self.team, name="event")
        property_definition = PropertyDefinition.objects.create(team=self.team, name="property", id=event.id)
        unrelated = Tag.objects.create(team=self.team, name="unrelated")
        for obj in [dashboard, insight, event, property_definition]:
            obj.tagged_items.create(tag=self.source)
        dashboard.tagged_items.create(tag=self.target)
        event.tagged_items.create(tag=self.target)
        event.tagged_items.create(tag=unrelated)

        preview = get_merge_preview(self.team.id, self.source.id, self.target.id)
        self.assertEqual(
            (preview.source_count, preview.target_count, preview.overlap_count, preview.result_count), (4, 2, 2, 4)
        )
        with patch("posthog.tag_management.MAX_SYNC_TAG_ASSIGNMENTS", 4):
            result = merge_tags(self.team.id, self.source.id, self.target.id, self.user)

        self.assertEqual((result.moved_count, result.overlap_count, result.usage_count), (2, 2, 4))
        self.assertEqual(result.tag.id, self.target.id)
        self.assertFalse(Tag.objects.filter(id=self.source.id).exists())
        for obj in [dashboard, insight, event, property_definition]:
            self.assertEqual(obj.tagged_items.filter(tag=self.target).count(), 1)
        self.assertTrue(event.tagged_items.filter(tag=unrelated).exists())

    def test_merge_uses_current_assignments(self) -> None:
        get_merge_preview(self.team.id, self.source.id, self.target.id)
        event = EventDefinition.objects.create(team=self.team, name="late")
        event.tagged_items.create(tag=self.source)
        result = merge_tags(self.team.id, self.source.id, self.target.id, self.user)
        self.assertEqual(result.moved_count, 1)
        self.assertTrue(event.tagged_items.filter(tag=self.target).exists())

    def test_preview_counts_assignments_in_one_statement(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        dashboard.tagged_items.create(tag=self.target)
        with CaptureQueriesContext(connection) as queries:
            preview = get_merge_preview(self.team.id, self.source.id, self.target.id)
        self.assertEqual(
            (preview.source_count, preview.target_count, preview.overlap_count, preview.result_count), (1, 1, 1, 1)
        )
        self.assertEqual(sum('FROM "posthog_taggeditem"' in query["sql"] for query in queries), 1)

    def test_mutations_ignore_assignment_reads_routed_to_replica(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        normal_read = router.db_for_read

        def read_from_replica(model, **hints):
            return "replica" if model in {Tag, TaggedItem} else normal_read(model, **hints)

        with patch.object(router, "db_for_read", side_effect=read_from_replica):
            self.assertEqual(TaggedItem.objects.all().db, "replica")
            self.assertEqual(delete_unused_tags(self.team.id, [self.source.id]), [])
            with self.assertRaises(ValidationError):
                delete_unused_tag(self.team.id, self.source.id, self.user)
            result = merge_tags(self.team.id, self.source.id, self.target.id, self.user)
            self.assertEqual(result.moved_count, 1)
            self.assertTrue(dashboard.tagged_items.using(DEFAULT_DB_ALIAS).filter(tag=self.target).exists())
            stale_assignment = TaggedItem(tag_id=self.source.id)
            with self.assertRaisesMessage(ValidationError, "This tag no longer exists"):
                TaggedItem.objects.bulk_create([stale_assignment])

    def test_mutation_and_logs_roll_back_together(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        before = list(ActivityLog.objects.values_list("id", flat=True))
        with self.assertRaises(RuntimeError), transaction.atomic():
            merge_tags(self.team.id, self.source.id, self.target.id, self.user)
            raise RuntimeError("rollback")
        self.assertTrue(Tag.objects.filter(id=self.source.id).exists())
        self.assertTrue(dashboard.tagged_items.filter(tag=self.source).exists())
        self.assertFalse(dashboard.tagged_items.filter(tag=self.target).exists())
        self.assertCountEqual(ActivityLog.objects.values_list("id", flat=True), before)

    def test_failure_after_relationship_writes_rolls_back(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        before = TaggedItem.objects.count()
        with patch.object(Tag, "delete", side_effect=RuntimeError("delete failed")):
            with self.assertRaises(RuntimeError):
                merge_tags(self.team.id, self.source.id, self.target.id, self.user)
        self.assertEqual(TaggedItem.objects.count(), before)
        self.assertTrue(dashboard.tagged_items.filter(tag=self.source).exists())

    @parameterized.expand(["project-group:internal", "", "   ", "customer"])
    def test_rename_rejects_reserved_blank_and_existing_names(self, name: str) -> None:
        with self.assertRaises(ValidationError):
            rename_tag(self.team.id, self.source.id, name, self.user)
        self.source.refresh_from_db()
        self.assertEqual(self.source.name, "customers")

    def test_rename_normalizes_and_preserves_assignments(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        item = dashboard.tagged_items.create(tag=self.source)
        with patch("posthog.tag_management.MAX_SYNC_TAG_ASSIGNMENTS", 1):
            renamed = rename_tag(self.team.id, self.source.id, "  New name  ", self.user)
        self.assertEqual(renamed.name, "new name")
        self.assertTrue(dashboard.tagged_items.filter(tag_id=self.source.id).exists())
        log = ActivityLog.objects.get(scope="TaggedItem", activity="updated", item_id=str(item.id))
        assert log.detail is not None
        self.assertEqual(log.detail["changes"][0]["before"], "customers")
        self.assertEqual(log.detail["changes"][0]["after"], "new name")
        self.assertEqual(log.detail["context"]["related_object_type"], "dashboard")
        self.assertEqual(log.detail["context"]["related_object_id"], str(dashboard.id))

    @parameterized.expand(["rename", "merge"])
    def test_assignment_limit_rejects_before_acquiring_project_lock(self, operation: str) -> None:
        for name in ["first", "second"]:
            dashboard = Dashboard.objects.create(team=self.team, name=name)
            dashboard.tagged_items.create(tag=self.source)
        with patch("posthog.tag_management.MAX_SYNC_TAG_ASSIGNMENTS", 1), CaptureQueriesContext(connection) as queries:
            with self.assertRaisesMessage(ValidationError, "assignment limit"):
                if operation == "rename":
                    rename_tag(self.team.id, self.source.id, "after", self.user)
                else:
                    merge_tags(self.team.id, self.source.id, self.target.id, self.user)
        self.assertFalse(any("pg_advisory_xact_lock" in query["sql"] for query in queries))
        self.source.refresh_from_db()
        self.assertEqual(self.source.name, "customers")
        self.assertEqual(TaggedItem.objects.filter(tag=self.source).count(), 2)

    def test_noop_rename_succeeds_above_assignment_limit(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        with patch("posthog.tag_management.MAX_SYNC_TAG_ASSIGNMENTS", 0):
            tag = rename_tag(self.team.id, self.source.id, "  Customers  ", self.user)
        self.assertEqual(tag.id, self.source.id)
        self.assertEqual(tag.name, "customers")

    @parameterized.expand(["rename", "merge"])
    @override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True, TEST=False)
    def test_relationship_audit_failure_rolls_back_management_write(self, operation: str) -> None:
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Example account")
        account.tagged_items.create(tag=self.source)
        initial_logs = list(ActivityLog.objects.values_list("id", flat=True))

        def fail_audit_insert(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "posthog_activitylog"'):
                raise DatabaseError("audit insert failed")
            return execute(sql, params, many, context)

        with (
            connection.execute_wrapper(fail_audit_insert),
            self.assertRaisesMessage(DatabaseError, "audit insert failed"),
        ):
            if operation == "rename":
                rename_tag(self.team.id, self.source.id, "after", self.user)
            else:
                merge_tags(self.team.id, self.source.id, self.target.id, self.user)

        self.source.refresh_from_db()
        self.assertEqual(self.source.name, "customers")
        self.assertTrue(account.tagged_items.filter(tag=self.source).exists())
        self.assertFalse(account.tagged_items.filter(tag=self.target).exists())
        self.assertCountEqual(ActivityLog.objects.values_list("id", flat=True), initial_logs)

    def test_cleanup_rechecks_usage_and_preserves_other_team(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.target)
        other_team = Team.objects.create(organization=self.organization)
        other = Tag.objects.create(team=other_team, name="other")
        deleted = delete_unused_tags(self.team.id, [self.source.id, self.target.id, other.id])
        self.assertEqual(deleted, [self.source.id])
        self.assertTrue(Tag.objects.filter(id=self.target.id).exists())
        self.assertTrue(Tag.objects.filter(id=other.id).exists())

    def test_management_rejects_cross_team_and_reserved_tags(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        other = Tag.objects.create(team=other_team, name="other")
        system = Tag.objects.create(team=self.team, name="project-group:internal")
        for target_id in [other.id, system.id, self.source.id, UUID(int=0)]:
            with self.subTest(target_id=target_id), self.assertRaises((Tag.DoesNotExist, ValidationError)):
                merge_tags(self.team.id, self.source.id, target_id, self.user)

    def test_assignment_lock_accepts_bigint_parent_team_column(self) -> None:
        # Production created parent_team_id as bigint, while the test schema builds it as integer.
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE posthog_team ALTER COLUMN parent_team_id TYPE bigint")
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)

        tag, created = Tag.objects.get_or_create(team_id=child.id, name="from child")

        self.assertTrue(created)
        self.assertEqual(tag.team_id, self.team.id)


class TestTagManagementTransactions(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _wait_for_blocked_writer(self, pid: int) -> None:
        def blocked() -> bool:
            with connection.cursor() as cursor:
                cursor.execute("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = %s", [pid])
                row = cursor.fetchone()
                return bool(row and row[0])

        wait_until(blocked, timeout=10, message="tag writer did not wait for the tag lock")

    @parameterized.expand(["rename", "merge"])
    def test_assignment_limit_rechecks_growth_while_waiting_for_project_lock(self, operation: str) -> None:
        source = Tag.objects.create(team=self.team, name="source")
        target = Tag.objects.create(team=self.team, name="target")
        first = Dashboard.objects.create(team=self.team, name="first")
        second = Dashboard.objects.create(team=self.team, name="second")
        first.tagged_items.create(tag=source)
        ready = Event()
        pids: list[int] = []

        def mutate() -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready.set()
                if operation == "rename":
                    rename_tag(self.team.id, source.id, "after", self.user)
                else:
                    merge_tags(self.team.id, source.id, target.id, self.user)
            finally:
                connection.close()

        with (
            patch("posthog.tag_management.MAX_SYNC_TAG_ASSIGNMENTS", 1),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            with tag_assignment_transaction([self.team.id]):
                future = executor.submit(mutate)
                self.assertTrue(ready.wait(10))
                self._wait_for_blocked_writer(pids[0])
                second.tagged_items.create(tag=source)
            with self.assertRaisesMessage(ValidationError, "assignment limit"):
                future.result(timeout=10)
        source.refresh_from_db()
        self.assertEqual(source.name, "source")
        self.assertEqual(TaggedItem.objects.filter(tag=source).count(), 2)
        self.assertFalse(TaggedItem.objects.filter(tag=target).exists())

    def test_notebook_clear_waits_for_merge_before_reading_assignments(self) -> None:
        source = Tag.objects.create(team=self.team, name="source")
        target = Tag.objects.create(team=self.team, name="target")
        notebook = Notebook.objects.create(team=self.team, title="Example notebook")
        notebook.tagged_items.create(tag=source)
        ready = Event()
        pids: list[int] = []

        def clear_tags() -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready.set()
                set_notebook_tags(notebook, [])
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with tag_assignment_transaction([self.team.id]):
                future = executor.submit(clear_tags)
                self.assertTrue(ready.wait(10))
                self._wait_for_blocked_writer(pids[0])
                merge_tags(self.team.id, source.id, target.id, self.user)
            future.result(timeout=10)
        self.assertFalse(notebook.tagged_items.exists())

    def test_name_creation_takes_advisory_lock_before_rename_can_wait_on_unique_index(self) -> None:
        source = Tag.objects.create(team=self.team, name="before")
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        ready = Event()
        pids: list[int] = []

        def rename() -> str:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready.set()
                with self.assertRaisesMessage(ValidationError, "A tag with this name already exists"):
                    rename_tag(self.team.id, source.id, "claimed", self.user)
                return "conflict"
            finally:
                connection.close()

        def waiting_on_advisory_lock() -> bool:
            with connection.cursor() as cursor:
                cursor.execute("SELECT wait_event FROM pg_stat_activity WHERE pid = %s", [pids[0]])
                return cursor.fetchone() == ("advisory",)

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                tag, created = Tag.objects.get_or_create(team_id=self.team.id, name="claimed")
                self.assertTrue(created)
                future = executor.submit(rename)
                self.assertTrue(ready.wait(10))
                self._wait_for_blocked_writer(pids[0])
                self.assertTrue(waiting_on_advisory_lock(), "rename waited on a row or unique index instead")
                TaggedItem.objects.bulk_create([TaggedItem.for_content_object(tag, dashboard)])
            self.assertEqual(future.result(timeout=10), "conflict")
        self.assertTrue(dashboard.tagged_items.filter(tag=tag).exists())

    @parameterized.expand(["rename", "cleanup", "assign"])
    def test_tag_row_locks_do_not_block_unrelated_team_fk_insert(self, operation: str) -> None:
        tag = Tag.objects.create(team=self.team, name="before")
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")

        def insert_dashboard() -> int:
            try:
                return Dashboard.objects.create(team_id=self.team.id, name="unrelated").id
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                if operation == "rename":
                    rename_tag(self.team.id, tag.id, "after", self.user)
                elif operation == "cleanup":
                    self.assertEqual(delete_unused_tags(self.team.id, [tag.id]), [tag.id])
                else:
                    dashboard.tagged_items.create(tag=tag)
                unrelated_id = executor.submit(insert_dashboard).result(timeout=5)
                self.assertNotEqual(unrelated_id, dashboard.id)

    def test_merge_publishes_completion_only_after_outer_commit(self) -> None:
        source = Tag.objects.create(team=self.team, name="source")
        target = Tag.objects.create(team=self.team, name="target")

        events: list[tuple[str, str]] = []
        with patch(
            "products.cdp.backend.internal_events.produce_internal_event",
            side_effect=lambda **kwargs: events.append(
                (kwargs["event"].properties["scope"], kwargs["event"].properties["activity"])
            ),
        ):
            with transaction.atomic():
                merge_tags(self.team.id, source.id, target.id, self.user)
                self.assertTrue(ActivityLog.objects.filter(scope="Tag", activity="merged", item_id=source.id).exists())
                self.assertEqual(events, [])
                transaction.set_rollback(True)
            self.assertEqual(events, [])
            self.assertFalse(ActivityLog.objects.filter(scope="Tag", activity="merged", item_id=source.id).exists())

            with transaction.atomic():
                merge_tags(self.team.id, source.id, target.id, self.user)
                self.assertEqual(events, [])
            self.assertEqual(events, [("Tag", "merged")])

    def test_cleanup_waiting_for_merge_rechecks_destination(self) -> None:
        source = Tag.objects.create(team=self.team, name="source")
        target = Tag.objects.create(team=self.team, name="target")
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=source)
        ready = Event()
        pids: list[int] = []

        def cleanup() -> list[UUID]:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready.set()
                return delete_unused_tags(self.team.id, [target.id])
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with tag_assignment_transaction([self.team.id]):
                list(Tag.objects.filter(id__in=[source.id, target.id]).order_by("id").select_for_update())
                future = executor.submit(cleanup)
                self.assertTrue(ready.wait(10))
                self._wait_for_blocked_writer(pids[0])
                merge_tags(self.team.id, source.id, target.id, self.user)
            self.assertEqual(future.result(timeout=10), [])
        self.assertTrue(Tag.objects.filter(id=target.id).exists())
        self.assertTrue(dashboard.tagged_items.filter(tag=target).exists())

    @parameterized.expand([False, True])
    def test_assignment_waits_for_cleanup_lock_and_survives(self, bulk: bool) -> None:
        tag = Tag.objects.create(team=self.team, name="target")
        first = Dashboard.objects.create(team=self.team, name="first")
        second = Dashboard.objects.create(team=self.team, name="second")
        first.tagged_items.create(tag=tag)
        ready = Event()
        pids: list[int] = []

        def assign() -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready.set()
                if bulk:
                    TaggedItem.objects.bulk_create([TaggedItem.for_content_object(tag, second)])
                else:
                    second.tagged_items.create(tag=tag)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with tag_assignment_transaction([self.team.id]):
                Tag.objects.select_for_update().get(id=tag.id)
                future = executor.submit(assign)
                self.assertTrue(ready.wait(10))
                self._wait_for_blocked_writer(pids[0])
                self.assertEqual(delete_unused_tags(self.team.id, [tag.id]), [])
            future.result(timeout=10)
        self.assertEqual(tag.tagged_items.count(), 2)

    @parameterized.expand([False, True])
    def test_merge_waits_for_assignment_and_moves_the_committed_row(self, bulk: bool) -> None:
        source = Tag.objects.create(team=self.team, name="source")
        target = Tag.objects.create(team=self.team, name="target")
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        ready = Event()
        pids: list[int] = []

        def merge() -> TagMergeResult:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                ready.set()
                return merge_tags(self.team.id, source.id, target.id, self.user)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                if bulk:
                    TaggedItem.objects.bulk_create([TaggedItem.for_content_object(source, dashboard)])
                else:
                    dashboard.tagged_items.create(tag=source)
                future = executor.submit(merge)
                self.assertTrue(ready.wait(10))
                self._wait_for_blocked_writer(pids[0])
            result = future.result(timeout=10)
        self.assertEqual(result.moved_count, 1)
        self.assertTrue(dashboard.tagged_items.filter(tag=target).exists())
        self.assertFalse(Tag.objects.filter(id=source.id).exists())
