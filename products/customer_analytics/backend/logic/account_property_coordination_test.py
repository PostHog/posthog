import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from inspect import unwrap
from queue import Queue
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import DataError, connections, transaction
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast

from posthog.models import Team

from products.customer_analytics.backend.facade.api import list_custom_property_sync_runs, update_custom_property_source
from products.customer_analytics.backend.facade.temporal_contracts import AccountPropertySyncWork
from products.customer_analytics.backend.logic.account_property_coordination import (
    AccountPropertySyncRead,
    AccountPropertySyncReadChanged,
    AccountPropertySyncSuperseded,
    assert_account_property_sync_read_current,
    begin_account_property_sync_attempt,
    begin_account_property_sync_read,
    finish_account_property_sync,
    get_account_property_snapshot_path,
    get_next_account_property_sync,
    get_source_mapping_key,
    guard_account_property_sync_attempt,
    list_pending_account_property_syncs,
    record_account_property_publication,
    request_account_property_sync,
    set_account_property_snapshot_path,
    set_coordinated_source_value,
)
from products.customer_analytics.backend.logic.account_property_runs import (
    AccountPropertySyncRunContext,
    AccountPropertySyncRunOutcome,
    finish_account_property_sync_runs,
    start_account_property_sync_runs,
)
from products.customer_analytics.backend.logic.custom_property_sync import sync_custom_property_values
from products.customer_analytics.backend.logic.custom_property_values import set_account_custom_properties_by_id
from products.customer_analytics.backend.models import (
    AccountPropertySyncPublication,
    AccountPropertySyncRequest,
    AccountPropertySyncState,
    AccountPropertySyncValueState,
    CustomPropertySource,
    CustomPropertySyncRun,
    CustomPropertyValue,
)
from products.customer_analytics.backend.models.custom_property_sync_run import SyncSegment
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_custom_property_definition,
    create_saved_query,
    saved_query_columns,
)
from products.data_warehouse.backend.logic.data_load.create_table import _publish_table_for_saved_query
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

_EXECUTE = "products.customer_analytics.backend.logic.custom_property_sync.execute_hogql_query"


@override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=True)
class AccountPropertyCoordinationTest(TeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = create_saved_query(
            team_id=self.team.id,
            name="billing_accounts",
            columns=saved_query_columns(["external_id", "organization_id", "plan", "new_plan", "region"]),
        )
        self.view_id = str(self.view.id)
        self.account = create_account(team_id=self.team.id, external_id="example-account")
        self.source = self._source()

    def _source(self, *, column: str = "plan", enabled: bool = True) -> CustomPropertySource:
        definition = create_custom_property_definition(team_id=self.team.id, name=column)
        return CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=definition,
            saved_query=self.view,
            key_column="external_id",
            source_column=column,
            is_enabled=enabled,
        )

    def _request(self, job_id: str | None = None) -> str:
        return request_account_property_sync(team_id=self.team.id, saved_query_id=self.view_id, job_id=job_id)

    def _next(self) -> AccountPropertySyncWork:
        work = get_next_account_property_sync(team_id=self.team.id, saved_query_id=self.view_id)
        assert work is not None
        return work

    def _attempt(self, request_id: str, segment: str = "live") -> AccountPropertySyncRead:
        return begin_account_property_sync_attempt(
            team_id=self.team.id, saved_query_id=self.view_id, request_id=request_id, segment=segment
        )

    def _read(self) -> AccountPropertySyncRead:
        return begin_account_property_sync_read(team_id=self.team.id, saved_query_id=self.view_id)

    def _finish(self, request_id: str, error: str | None = None) -> None:
        finish_account_property_sync(
            team_id=self.team.id, saved_query_id=self.view_id, request_id=request_id, error=error
        )

    def _set(self, read: AccountPropertySyncRead, value: str | None) -> bool | None:
        return set_coordinated_source_value(read=read, source=self.source, account_id=self.account.id, value=value)

    def _active_value(self, account_id: UUID | None = None, source: CustomPropertySource | None = None) -> str | None:
        return (
            CustomPropertyValue.objects.for_team(self.team.id)
            .filter(
                account_id=account_id or self.account.id,
                definition_id=(source or self.source).definition_id,
                is_deleted=False,
            )
            .values_list("value_str", flat=True)
            .first()
        )

    def _publication(self, job_id: str) -> None:
        assert record_account_property_publication(team_id=self.team.id, saved_query_id=self.view_id, job_id=job_id)

    @parameterized.expand([("completed", None), ("failed", "warehouse unavailable")])
    def test_bursts_coalesce_but_changes_during_active_work_survive_finish(self, _name: str, error: str | None) -> None:
        first_id = self._request()
        assert {self._request() for _ in range(4)} == {first_id}
        assert (self.team.id, self.view_id) in list_pending_account_property_syncs()
        first = self._next()
        assert first.request_id == first_id
        assert self._next() == first

        followup_id = self._request()
        assert followup_id != first_id
        assert {self._request() for _ in range(4)} == {followup_id}
        assert self._next() == first
        requests = AccountPropertySyncRequest.objects.for_team(self.team.id).filter(saved_query_id=self.view_id)
        assert requests.count() == 2
        assert requests.get(id=followup_id).status == AccountPropertySyncRequest.Status.PENDING

        self._finish(first_id, error)
        first_request = requests.get(id=first_id)
        assert first_request.status == (
            AccountPropertySyncRequest.Status.FAILED if error else AccountPropertySyncRequest.Status.COMPLETED
        )
        assert first_request.error == error
        assert first_request.finished_at is not None
        assert (self.team.id, self.view_id) in list_pending_account_property_syncs()
        followup = self._next()
        assert followup.request_id == followup_id
        assert followup.generation > first.generation
        assert self._next() == followup
        self._finish(followup_id)
        assert get_next_account_property_sync(team_id=self.team.id, saved_query_id=self.view_id) is None
        assert (self.team.id, self.view_id) not in list_pending_account_property_syncs()

    def test_deferred_coordinated_runs_do_not_expire_as_broken_source_failures(self) -> None:
        self._request()
        work = self._next()
        start_account_property_sync_runs(
            AccountPropertySyncRunContext(team_id=self.team.id, saved_query_id=self.view_id, job_id=work.job_id),
            workflow_id="coordinator",
            workflow_run_id=None,
        )
        CustomPropertySyncRun.objects.for_team(self.team.id).filter(job_id=work.job_id).update(
            started_at=timezone.now() - timedelta(days=2)
        )
        runs, total = list_custom_property_sync_runs(self.team.id, str(self.source.id), offset=0, limit=10)
        assert total == 2
        assert all(run.status == "running" for run in runs)
        assert (
            CustomPropertySyncRun.objects.for_team(self.team.id).filter(job_id=work.job_id, status="running").count()
            == 2
        )
        self.source.refresh_from_db()
        assert self.source.consecutive_failures == 0
        assert self.source.is_enabled

    def test_old_mapping_failure_stays_visible_without_disabling_the_new_mapping(self) -> None:
        self.source.consecutive_failures = 4
        self.source.save(update_fields=["consecutive_failures"])
        self._request()
        work = self._next()
        context = AccountPropertySyncRunContext(team_id=self.team.id, saved_query_id=self.view_id, job_id=work.job_id)
        start_account_property_sync_runs(context, workflow_id="coordinator", workflow_run_id=None)
        mapping_keys = {str(self.source.id): get_source_mapping_key(self.source)}
        assert (
            update_custom_property_source(
                team_id=self.team.id, source_id=str(self.source.id), fields={"source_column": "new_plan"}
            )
            is not None
        )
        outcome = AccountPropertySyncRunOutcome(
            source_id=self.source.id, rows_read=1, changed=1, matched=1, written=0, error="Invalid source value."
        )
        for segment in SyncSegment:
            finish_account_property_sync_runs(context, segment, [outcome], source_mapping_keys=mapping_keys)
        self.source.refresh_from_db()
        assert self.source.is_enabled
        assert self.source.consecutive_failures == 4
        assert (
            CustomPropertySyncRun.objects.for_team(self.team.id)
            .filter(job_id=work.job_id, status="failed", error="Invalid source value.")
            .count()
            == 2
        )

    @parameterized.expand([("source_column", "new_plan"), ("key_column", "organization_id")])
    def test_followup_loads_current_mapping_and_captured_mapping_cannot_write(self, field: str, value: str) -> None:
        first_id = self._request()
        self._next()
        old_read = self._attempt(first_id)
        assert self._set(old_read, "old") is True
        set_account_property_snapshot_path(old_read, self.source, "snapshots/old.parquet")

        updated = update_custom_property_source(
            team_id=self.team.id, source_id=str(self.source.id), fields={field: value}
        )
        assert updated is not None
        assert self._set(old_read, "obsolete mapping") is None
        assert self._active_value() == "old"
        assert self._next().request_id == first_id
        self._finish(first_id, "mapping changed during read")
        followup = self._next()
        assert followup.request_id != first_id
        read = self._attempt(followup.request_id)
        current_source = (
            CustomPropertySource.objects.for_team(self.team.id).select_related("definition").get(id=self.source.id)
        )
        assert get_account_property_snapshot_path(read, current_source) is None

        row = {"external_id": self.account.external_id, "organization_id": self.account.external_id}
        row["plan"] = "fresh" if field == "key_column" else "obsolete mapping"
        row["new_plan"] = "fresh"

        def execute(query: ast.SelectQuery, **kwargs: object) -> SimpleNamespace:
            columns = []
            for item in query.select:
                assert isinstance(item, ast.Field)
                column = item.chain[0]
                assert isinstance(column, str)
                columns.append(row[column])
            return SimpleNamespace(results=[columns])

        with patch(_EXECUTE, side_effect=execute):
            result = sync_custom_property_values(team_id=self.team.id, saved_query_id=self.view_id, sync_read=read)

        assert result.source_errors == {}
        assert result.written == 1
        assert self._active_value() == "fresh"
        set_account_property_snapshot_path(read, current_source, "snapshots/current.parquet")
        assert get_account_property_snapshot_path(read, current_source) == "snapshots/current.parquet"
        assert self._set(read, "obsolete mapping") is None
        assert self._active_value() == "fresh"

    @parameterized.expand(
        [
            ("published_set", "published", "old", "new", True),
            ("published_clear", "published", "old", None, True),
            ("published_noop", "published", "new", "new", False),
            ("published_absent_clear", "published", None, None, False),
            ("legacy_noop", "legacy", "new", "new", False),
            ("same_revision_noop", "inline", "new", "new", False),
            ("same_revision_absent_clear", "inline", None, None, False),
        ]
    )
    def test_older_inputs_cannot_undo_newer_inline_value_or_noop(
        self, _name: str, older_kind: str, initial: str | None, latest: str | None, written: bool
    ) -> None:
        if older_kind != "legacy":
            self._publication("older-publication")
        old_inline = self._read()
        if initial is not None:
            assert self._set(old_inline, initial) is True
        if older_kind != "inline":
            self._publication("current-publication")
        current = self._read()
        assert self._set(current, latest) is written
        history = CustomPropertyValue.objects.for_team(self.team.id).filter(
            account_id=self.account.id, definition_id=self.source.definition_id
        )
        history_count = history.count()

        if older_kind == "inline":
            stale = old_inline
        else:
            self._finish(self._next().request_id)
            job_id = "older-publication" if older_kind == "published" else "unidentified-legacy-job"
            request_id = self._request(job_id)
            assert self._request(job_id) == request_id
            work = self._next()
            assert work.request_id == request_id
            assert work.generation > current.generation
            stale = self._attempt(request_id, "tracked")
            assert stale.snapshot_revision < current.snapshot_revision

        assert self._set(stale, "stale value") is None
        assert self._set(stale, None) is None
        assert self._active_value() == latest
        assert history.count() == history_count
        accepted = AccountPropertySyncValueState.objects.for_team(self.team.id).get(
            account_id=self.account.id, definition_id=self.source.definition_id
        )
        assert (accepted.snapshot_revision, accepted.generation) == (current.snapshot_revision, current.generation)

    @parameterized.expand([("set", "direct"), ("clear", None), ("absent_clear", None)])
    def test_direct_writes_reject_preexisting_reads_but_allow_a_fresh_read(
        self, operation: str, value: str | None
    ) -> None:
        self._publication("current-publication")
        older = self._read()
        if operation != "absent_clear":
            assert self._set(older, "initial") is True
        set_account_custom_properties_by_id(
            team_id=self.team.id,
            account_id=self.account.id,
            properties={str(self.source.definition_id): value},
        )
        assert self._set(older, "obsolete") is None
        assert self._active_value() == value
        assert self._set(self._read(), "fresh") is True
        assert self._active_value() == "fresh"

    def test_publications_while_disabled_still_fence_late_staged_inputs_after_reenable(self) -> None:
        self._publication("older-publication")
        self._finish(self._next().request_id)
        assert (
            update_custom_property_source(
                team_id=self.team.id, source_id=str(self.source.id), fields={"is_enabled": False}
            )
            is not None
        )
        self._publication("newer-publication")
        assert get_next_account_property_sync(team_id=self.team.id, saved_query_id=self.view_id) is None
        assert (
            update_custom_property_source(
                team_id=self.team.id, source_id=str(self.source.id), fields={"is_enabled": True}
            )
            is not None
        )
        current = self._read()
        assert current.snapshot_revision == 2
        assert self._set(current, "newer") is True
        self._finish(self._next().request_id)
        request_id = self._request("older-publication")
        self._next()
        older = self._attempt(request_id, "tracked")
        assert older.snapshot_revision == 1
        assert self._set(older, "obsolete") is None
        assert self._active_value() == "newer"

    def test_unidentified_staged_jobs_fill_missing_keys_but_never_replace_an_accepted_epoch_zero_key(self) -> None:
        first_id = self._request("legacy-first")
        self._next()
        first = self._attempt(first_id, "tracked")
        assert self._set(first, "accepted") is True
        self._finish(first_id)

        second_id = self._request("legacy-second")
        self._next()
        second = self._attempt(second_id, "tracked")
        assert second.generation > first.generation
        assert self._set(second, "replacement") is None
        assert self._set(second, None) is None
        other = create_account(team_id=self.team.id, external_id="previously-unseen")
        assert (
            set_coordinated_source_value(
                read=second, source=self.source, account_id=other.id, value="first observation"
            )
            is True
        )
        assert self._active_value() == "accepted"
        assert self._active_value(other.id) == "first observation"
        assert set(
            AccountPropertySyncValueState.objects.for_team(self.team.id).values_list("snapshot_revision", "generation")
        ) == {(0, 0)}

    def test_retry_revokes_only_its_segment_and_cannot_replace_values_or_snapshot_pointers(self) -> None:
        self._publication("published-job")
        self._finish(self._next().request_id)
        request_id = self._request("published-job")
        self._next()
        tracked = self._attempt(request_id, "tracked")
        ignored = self._attempt(request_id, "ignored")
        set_account_property_snapshot_path(tracked, self.source, "snapshots/tracked-original.parquet")
        set_account_property_snapshot_path(ignored, self.source, "snapshots/ignored-original.parquet")
        retry = self._attempt(request_id, "tracked")
        assert retry.token != tracked.token
        assert self._set(retry, "retry value") is True
        set_account_property_snapshot_path(retry, self.source, "snapshots/tracked-retry.parquet")

        with self.assertRaises(AccountPropertySyncSuperseded):
            self._set(tracked, "revoked value")
        with self.assertRaises(AccountPropertySyncSuperseded):
            set_account_property_snapshot_path(tracked, self.source, "snapshots/revoked.parquet")
        with self.assertRaises(AccountPropertySyncSuperseded):
            get_account_property_snapshot_path(tracked, self.source)
        assert self._active_value() == "retry value"
        assert get_account_property_snapshot_path(retry, self.source) == "snapshots/tracked-retry.parquet"
        assert get_account_property_snapshot_path(ignored, self.source) == "snapshots/ignored-original.parquet"
        other = create_account(team_id=self.team.id, external_id="ignored-account")
        assert (
            set_coordinated_source_value(read=ignored, source=self.source, account_id=other.id, value="ignored") is True
        )
        set_account_property_snapshot_path(ignored, self.source, "snapshots/ignored-current.parquet")
        assert get_account_property_snapshot_path(ignored, self.source) == "snapshots/ignored-current.parquet"
        assert get_account_property_snapshot_path(retry, self.source) == "snapshots/tracked-retry.parquet"

    @parameterized.expand([("completed", None), ("failed", "read failed")])
    def test_terminal_requests_revoke_writes_and_snapshot_publication(self, _name: str, error: str | None) -> None:
        request_id = self._request()
        self._next()
        read = self._attempt(request_id)
        assert self._set(read, "accepted") is True
        set_account_property_snapshot_path(read, self.source, "snapshots/accepted.parquet")
        self._finish(request_id, error)
        with self.assertRaises(AccountPropertySyncSuperseded):
            self._set(read, None)
        with self.assertRaises(AccountPropertySyncSuperseded):
            set_account_property_snapshot_path(read, self.source, "snapshots/terminal.parquet")
        with self.assertRaises(AccountPropertySyncSuperseded):
            self._attempt(request_id)
        assert self._active_value() == "accepted"
        next_id = self._request()
        self._next()
        current = self._attempt(next_id)
        assert get_account_property_snapshot_path(current, self.source) == "snapshots/accepted.parquet"

    @parameterized.expand([("account",), ("definition",)])
    def test_freshness_is_scoped_to_the_account_and_definition(self, other_key: str) -> None:
        older = self._read()
        current = self._read()
        assert self._set(current, "current") is True
        assert self._set(older, "obsolete") is None
        account = self.account
        source = self.source
        if other_key == "account":
            account = create_account(team_id=self.team.id, external_id="another-account")
        else:
            source = self._source(column="region")
        assert (
            set_coordinated_source_value(read=older, source=source, account_id=account.id, value="independent") is True
        )
        assert self._active_value() == "current"
        assert self._active_value(account.id, source) == "independent"

    @parameterized.expand([("team",), ("view",)])
    def test_requests_and_attempts_are_scoped_to_team_and_view(self, other_scope: str) -> None:
        team_id = self.team.id
        view_id = self.view_id
        if other_scope == "team":
            team_id = Team.objects.create(organization=self.organization, name="Other project").id
        else:
            view_id = str(create_saved_query(team_id=self.team.id, name="other_accounts").id)
        first_id = self._request()
        other_id = request_account_property_sync(team_id=team_id, saved_query_id=view_id)
        assert other_id != first_id
        assert self._request() == first_id
        assert request_account_property_sync(team_id=team_id, saved_query_id=view_id) == other_id
        self._next()
        first_read = self._attempt(first_id)
        other_work = get_next_account_property_sync(team_id=team_id, saved_query_id=view_id)
        assert other_work is not None and other_work.request_id == other_id
        with self.assertRaises(AccountPropertySyncRequest.DoesNotExist):
            begin_account_property_sync_attempt(
                team_id=team_id, saved_query_id=view_id, request_id=first_id, segment="live"
            )
        other_read = begin_account_property_sync_read(team_id=team_id, saved_query_id=view_id)
        with self.assertRaises(ValueError):
            self._set(other_read, "wrong source")
        finish_account_property_sync(team_id=team_id, saved_query_id=view_id, request_id=other_id)
        assert self._next().request_id == first_id
        assert self._set(first_read, "still valid") is True
        assert self._active_value() == "still valid"

    def test_source_enabled_while_pending_is_included_without_an_extra_request(self) -> None:
        region = self._source(column="region", enabled=False)
        request_id = self._request()
        assert (
            update_custom_property_source(team_id=self.team.id, source_id=str(region.id), fields={"is_enabled": True})
            is not None
        )
        assert self._request() == request_id
        assert (
            AccountPropertySyncRequest.objects.for_team(self.team.id).filter(saved_query_id=self.view_id).count() == 1
        )
        work = self._next()
        read = self._attempt(work.request_id)
        with patch(_EXECUTE, return_value=SimpleNamespace(results=[[self.account.external_id, "enterprise", "EMEA"]])):
            result = sync_custom_property_values(team_id=self.team.id, saved_query_id=self.view_id, sync_read=read)
        assert result.source_errors == {}
        assert result.written == 2
        assert self._active_value() == "enterprise"
        assert self._active_value(source=region) == "EMEA"

    @parameterized.expand([("empty", False), ("already_pending", True)])
    def test_rolled_back_source_enable_does_not_leave_or_replace_a_pending_request(
        self, _name: str, already_pending: bool
    ) -> None:
        region = self._source(column="region", enabled=False)
        existing_id = self._request() if already_pending else None
        with self.assertRaisesRegex(RuntimeError, "abort source edit"):
            with transaction.atomic():
                assert (
                    update_custom_property_source(
                        team_id=self.team.id, source_id=str(region.id), fields={"is_enabled": True}
                    )
                    is not None
                )
                rolled_back_id = self._request()
                raise RuntimeError("abort source edit")
        region.refresh_from_db()
        assert not region.is_enabled
        requests = AccountPropertySyncRequest.objects.for_team(self.team.id).filter(saved_query_id=self.view_id)
        assert list(requests.values_list("id", flat=True)) == ([UUID(existing_id)] if existing_id else [])
        if not already_pending:
            assert get_next_account_property_sync(team_id=self.team.id, saved_query_id=self.view_id) is None
        assert (
            update_custom_property_source(team_id=self.team.id, source_id=str(region.id), fields={"is_enabled": True})
            is not None
        )
        committed_id = self._request()
        if already_pending:
            assert committed_id == existing_id
        else:
            assert committed_id != rolled_back_id
        assert self._next().request_id == committed_id

    def test_publication_during_inline_network_read_defers_all_writes_and_keeps_durable_followup(self) -> None:
        self._publication("baseline-job")
        self._finish(self._next().request_id)
        read = self._read()
        assert_account_property_sync_read_current(read)

        def execute(*args: object, **kwargs: object) -> SimpleNamespace:
            self._publication("replacement-job")
            return SimpleNamespace(results=[[self.account.external_id, "obsolete"]])

        with patch(_EXECUTE, side_effect=execute):
            result = sync_custom_property_values(
                team_id=self.team.id, saved_query_id=self.view_id, external_id=self.account.external_id, sync_read=read
            )
        assert result.deferred == 1
        assert result.written == 0
        assert self._active_value() is None
        assert not AccountPropertySyncValueState.objects.for_team(self.team.id).exists()
        with self.assertRaises(AccountPropertySyncReadChanged):
            assert_account_property_sync_read_current(read)
        assert (self.team.id, self.view_id) in list_pending_account_property_syncs()
        work = self._next()
        current = self._attempt(work.request_id)
        assert current.snapshot_revision > read.snapshot_revision
        assert_account_property_sync_read_current(current)

    @parameterized.expand([("caller_rollback", False), ("pointer_save_failure", True)])
    def test_publication_pointer_revision_and_outbox_share_the_publish_transaction(
        self, _name: str, save_failure: bool
    ) -> None:
        table = DataWarehouseTable.objects.create(
            team_id=self.team.id,
            name=self.view.name,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://example.com/accounts/*.parquet",
            queryable_folder="baseline-folder",
            created_via=DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW,
        )
        self.view.table = table
        self.view.save(update_fields=["table", "updated_at"])
        publish = unwrap(_publish_table_for_saved_query)
        publish(table, team_id=self.team.id, saved_query_id=self.view_id, job_id="baseline-job")
        first = self._next()
        old_read = self._attempt(first.request_id)
        table.queryable_folder = "x" * 501 if save_failure else "rolled-back-folder"
        expected_error = DataError if save_failure else RuntimeError
        with self.assertRaises(expected_error):
            with transaction.atomic():
                publish(table, team_id=self.team.id, saved_query_id=self.view_id, job_id="failed-publication")
                raise RuntimeError("abort publication")
        table.refresh_from_db()
        assert table.queryable_folder == "baseline-folder"
        state = AccountPropertySyncState.objects.for_team(self.team.id).get(saved_query_id=self.view_id)
        assert state.publication_revision == old_read.snapshot_revision == 1
        assert (
            not AccountPropertySyncPublication.objects.for_team(self.team.id)
            .filter(job_id="failed-publication")
            .exists()
        )
        assert (
            AccountPropertySyncRequest.objects.for_team(self.team.id).filter(saved_query_id=self.view_id).count() == 1
        )
        assert_account_property_sync_read_current(old_read)

        table.queryable_folder = "current-folder"
        publish(table, team_id=self.team.id, saved_query_id=self.view_id, job_id="current-job")
        state.refresh_from_db()
        assert state.publication_revision == 2
        assert state.pending_live_request_id is not None
        pending_id = str(state.pending_live_request_id)
        assert AccountPropertySyncRequest.objects.for_team(self.team.id).get(id=pending_id).status == (
            AccountPropertySyncRequest.Status.PENDING
        )
        with self.assertRaises(AccountPropertySyncReadChanged):
            assert_account_property_sync_read_current(old_read)
        table.queryable_folder = "obsolete-retry-folder"
        publish(table, team_id=self.team.id, saved_query_id=self.view_id, job_id="baseline-job")
        table.refresh_from_db()
        assert table.queryable_folder == "current-folder"
        publish(table, team_id=self.team.id, saved_query_id=self.view_id, job_id="current-job")
        state.refresh_from_db()
        assert state.publication_revision == 2
        assert str(state.pending_live_request_id) == pending_id
        assert list(
            AccountPropertySyncPublication.objects.for_team(self.team.id)
            .filter(saved_query_id=self.view_id)
            .order_by("revision")
            .values_list("job_id", "revision")
        ) == [("baseline-job", 1), ("current-job", 2)]
        self._finish(first.request_id)
        followup = self._next()
        assert followup.request_id == pending_id
        assert self._attempt(pending_id).snapshot_revision == 2


@override_settings(ACCOUNT_PROPERTY_SYNC_COORDINATION_ENABLED=True)
class AccountPropertyAttemptConcurrencyTest(TeamScopedTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand([("independent_key", False), ("revocation", True)])
    def test_attempt_fence_allows_parallel_keys_but_holds_revocation_until_commit(
        self, _name: str, revoke: bool
    ) -> None:
        view = create_saved_query(team_id=self.team.id, name="concurrent_accounts")
        view_id = str(view.id)
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        source = CustomPropertySource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            definition=definition,
            saved_query=view,
            key_column="external_id",
            source_column="plan",
        )
        first = create_account(team_id=self.team.id, external_id="first")
        second = create_account(team_id=self.team.id, external_id="second")
        request_id = request_account_property_sync(team_id=self.team.id, saved_query_id=view_id, job_id="staged-job")
        assert get_next_account_property_sync(team_id=self.team.id, saved_query_id=view_id) is not None
        tracked = begin_account_property_sync_attempt(
            team_id=self.team.id, saved_query_id=view_id, request_id=request_id, segment="tracked"
        )
        ignored = begin_account_property_sync_attempt(
            team_id=self.team.id, saved_query_id=view_id, request_id=request_id, segment="ignored"
        )
        pids: Queue[int] = Queue()
        start = Barrier(2)

        def work() -> AccountPropertySyncRead | bool | None:
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
                start.wait(timeout=10)
                if revoke:
                    return begin_account_property_sync_attempt(
                        team_id=self.team.id, saved_query_id=view_id, request_id=request_id, segment="tracked"
                    )
                return set_coordinated_source_value(read=ignored, source=source, account_id=second.id, value="second")
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with guard_account_property_sync_attempt(tracked):
                assert (
                    set_coordinated_source_value(read=tracked, source=source, account_id=first.id, value="first")
                    is True
                )
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    holder_pid = cursor.fetchone()[0]
                future: Future[AccountPropertySyncRead | bool | None] = pool.submit(work)
                writer_pid = pids.get(timeout=10)
                assert writer_pid != holder_pid
                start.wait(timeout=10)
                if revoke:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        with connections["default"].cursor() as cursor:
                            cursor.execute("SELECT %s = ANY(pg_blocking_pids(%s))", [holder_pid, writer_pid])
                            if cursor.fetchone()[0]:
                                break
                        assert not future.done()
                    else:
                        self.fail("Attempt revocation did not wait for the current write")
                else:
                    assert future.result(timeout=10) is True
            outcome = future.result(timeout=10)
        if revoke:
            assert isinstance(outcome, AccountPropertySyncRead)
            with self.assertRaises(AccountPropertySyncSuperseded):
                set_coordinated_source_value(read=tracked, source=source, account_id=first.id, value="revoked")
        assert (
            CustomPropertyValue.objects.for_team(self.team.id)
            .get(account_id=first.id, definition_id=definition.id, is_deleted=False)
            .value_str
            == "first"
        )
