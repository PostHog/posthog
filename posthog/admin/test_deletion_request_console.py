from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.admin.console.panels import MAX_FACTS_PER_PANEL
from posthog.admin.console.registry import console
from posthog.models.data_deletion_request import (
    AdhocEventDeletionBacklog,
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
)

PANELS = "posthog.admin.console.deletion_request_panels"


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
@time_machine.travel("2026-11-06T12:00:00Z", tick=False)
class TestDeletionRequestConsole(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        clickhouse_team, _ = Group.objects.get_or_create(name="ClickHouse Team")
        self.user.groups.add(clickhouse_team)
        self.client.force_login(self.user)

    def _request(self, **fields) -> DataDeletionRequest:
        now = timezone.now()
        defaults = {
            "team_id": self.team.pk,
            "request_type": RequestType.EVENT_REMOVAL,
            "events": ["$pageview"],
            "start_time": now - timedelta(days=7),
            "end_time": now - timedelta(minutes=1),
            "status": RequestStatus.DRAFT,
        }
        return DataDeletionRequest.objects.create(**{**defaults, **fields})

    def _url(self, obj: DataDeletionRequest, panel: str = "", operation: str = "") -> str:
        url = f"/admin/console/deletion-requests/{obj.pk}/"
        return f"{url}{panel}/{operation}/" if operation else url

    def _preview_approval(self, obj: DataDeletionRequest, mode: ExecutionMode):
        revision = obj.criteria_updated_at.isoformat() if obj.criteria_updated_at else ""
        with patch(
            f"{PANELS}.count_adhoc_event_deletion_backlog", return_value=AdhocEventDeletionBacklog(total=5, for_team=2)
        ):
            return self.client.post(
                self._url(obj, "workflow", "approve"),
                {"execution_mode": mode.value, "criteria_revision": revision, "reason": "Ticket 123"},
            )

    def test_record_page_shows_the_request_and_django_admin_links_to_it(self) -> None:
        obj = self._request(status=RequestStatus.FAILED, attempt_count=2, last_dagster_run_id="run-1")

        response = self.client.get(self._url(obj))

        assert response.status_code == 200
        content = response.content.decode()
        for title in ("Overview", "ClickHouse stats", "Workflow", "Retry deletion", "Verify deletion"):
            assert title in content
        assert f"/admin/console/teams/{self.team.pk}/" in content
        for panel in console.panels_for("deletion-request"):
            assert len(panel.facts(obj)) <= MAX_FACTS_PER_PANEL, f"{panel.key} shows too many facts"
        admin_page = self.client.get(f"/admin/posthog/datadeletionrequest/{obj.pk}/change/").content.decode()
        assert self._url(obj) in admin_page

    @parameterized.expand(
        [
            ("event_removal_auto_approvable", RequestType.EVENT_REMOVAL, {}, False),
            ("event_removal_opted_out", RequestType.EVENT_REMOVAL, {"requires_approval": "on"}, True),
            # No checkbox for these. False would hide them from the changelist's "requires approval" filter.
            ("property_removal", RequestType.PROPERTY_REMOVAL, {}, True),
        ]
    )
    def test_submit_moves_a_draft_to_pending_and_records_the_opt_out(
        self, _name: str, request_type: RequestType, data: dict, requires_approval: bool
    ) -> None:
        obj = self._request(request_type=request_type, properties=["$ip"] if request_type != "event_removal" else [])

        response = self.client.post(self._url(obj, "workflow", "submit"), {"reason": "Customer asked", **data})

        assert response.status_code == 302
        obj.refresh_from_db()
        assert obj.status == RequestStatus.PENDING
        assert not obj.approved
        assert obj.requires_approval == requires_approval

    def test_submit_needs_a_reason(self) -> None:
        obj = self._request()

        response = self.client.post(self._url(obj, "workflow", "submit"), {"reason": " "})

        assert response.status_code == 400
        obj.refresh_from_db()
        assert obj.status == RequestStatus.DRAFT

    @parameterized.expand(
        [
            ("property_removal_without_properties", {"request_type": RequestType.PROPERTY_REMOVAL}),
            (
                "person_removal_without_targets",
                {"request_type": RequestType.PERSON_REMOVAL, "events": [], "person_drop_profiles": True},
            ),
            (
                "person_removal_without_drop_flag",
                {"request_type": RequestType.PERSON_REMOVAL, "events": [], "person_distinct_ids": ["user-1"]},
            ),
        ]
    )
    def test_an_incomplete_draft_cannot_be_submitted(self, _name: str, fields: dict) -> None:
        obj = self._request(**fields)

        response = self.client.post(self._url(obj, "workflow", "submit"), {"reason": "Customer asked"})

        assert response.status_code == 404
        obj.refresh_from_db()
        assert obj.status == RequestStatus.DRAFT
        assert "Cannot submit" in self.client.get(self._url(obj)).content.decode()

    @parameterized.expand(
        [
            ("event_removal_deferred", RequestType.EVENT_REMOVAL, ExecutionMode.DEFERRED, True),
            ("event_removal_immediate", RequestType.EVENT_REMOVAL, ExecutionMode.IMMEDIATE, True),
            ("query_backed_deferred", RequestType.HOGQL_EVENT_REMOVAL, ExecutionMode.DEFERRED, True),
            ("query_backed_never_immediate", RequestType.HOGQL_EVENT_REMOVAL, ExecutionMode.IMMEDIATE, False),
            ("property_removal_never_deferred", RequestType.PROPERTY_REMOVAL, ExecutionMode.DEFERRED, False),
            ("person_removal_immediate", RequestType.PERSON_REMOVAL, ExecutionMode.IMMEDIATE, True),
        ]
    )
    def test_approve_offers_only_the_execution_modes_the_type_supports(
        self, _name: str, request_type: RequestType, mode: ExecutionMode, allowed: bool
    ) -> None:
        obj = self._request(request_type=request_type, properties=["$ip"], status=RequestStatus.PENDING)

        preview = self._preview_approval(obj, mode)

        if not allowed:
            assert preview.status_code == 400
            obj.refresh_from_db()
            assert obj.status == RequestStatus.PENDING
            return
        assert preview.status_code == 200
        assert "5 events are queued for deletion" in preview.content.decode()
        obj.refresh_from_db()
        assert obj.status == RequestStatus.PENDING

        confirmed = self.client.post(
            self._url(obj, "workflow", "approve"), {"confirm_token": preview.context["confirm_token"]}
        )

        assert confirmed.status_code == 302
        obj.refresh_from_db()
        assert (obj.status, obj.execution_mode, obj.approved_by) == (RequestStatus.APPROVED, mode, self.user)
        assert LogEntry.objects.filter(object_id=str(obj.pk), change_message__startswith="Approved").exists()

    @parameterized.expand(
        [
            (
                "person_targets",
                {
                    "request_type": RequestType.PERSON_REMOVAL,
                    "person_distinct_ids": [f"user-{index}" for index in range(25)],
                    "person_drop_events": True,
                },
                ExecutionMode.IMMEDIATE,
                ["user-0", "user-19", "and 5 more"],
                ["user-24"],
            ),
            (
                "query_variables",
                {
                    "request_type": RequestType.HOGQL_EVENT_REMOVAL,
                    "hogql_query": "SELECT uuid FROM events WHERE timestamp < {cutoff}",
                    "hogql_variables": {"cutoff": "2026-01-01"},
                },
                ExecutionMode.DEFERRED,
                ["cutoff", "2026-01-01"],
                [],
            ),
        ]
    )
    def test_approve_preview_names_what_gets_deleted(
        self, _name: str, fields: dict, mode: ExecutionMode, shown: list[str], hidden: list[str]
    ) -> None:
        obj = self._request(status=RequestStatus.PENDING, **fields)

        content = self._preview_approval(obj, mode).content.decode()

        for text in shown:
            assert text in content
        for text in hidden:
            assert text not in content

    def test_approve_preview_still_shows_when_the_backlog_count_fails(self) -> None:
        obj = self._request(status=RequestStatus.PENDING)

        with patch(f"{PANELS}.count_adhoc_event_deletion_backlog", side_effect=Exception("ClickHouse is down")):
            response = self.client.post(
                self._url(obj, "workflow", "approve"),
                {"execution_mode": "deferred", "criteria_revision": "", "reason": "Ticket 123"},
            )

        assert response.status_code == 200
        assert "Could not count the events already queued for deletion" in response.content.decode()

    def test_an_approval_confirmed_for_one_request_cannot_approve_another(self) -> None:
        previewed = self._request(status=RequestStatus.PENDING)
        other = self._request(status=RequestStatus.PENDING)
        preview = self._preview_approval(previewed, ExecutionMode.DEFERRED)

        response = self.client.post(
            self._url(other, "workflow", "approve"), {"confirm_token": preview.context["confirm_token"]}
        )

        assert response.status_code == 302
        other.refresh_from_db()
        assert other.status == RequestStatus.PENDING

    @parameterized.expand([("criteria_never_edited", None), ("criteria_edited_before", timedelta(hours=1))])
    def test_an_approval_does_not_land_on_criteria_edited_after_the_preview(
        self, _name: str, edited_ago: timedelta | None
    ) -> None:
        obj = self._request(
            status=RequestStatus.PENDING,
            criteria_updated_at=timezone.now() - edited_ago if edited_ago else None,
        )
        preview = self._preview_approval(obj, ExecutionMode.DEFERRED)
        # An edit resets the request to draft. Submitting it again brings it back to pending with new criteria.
        DataDeletionRequest.objects.filter(pk=obj.pk).update(
            events=["$autocapture"], criteria_updated_at=timezone.now()
        )

        response = self.client.post(
            self._url(obj, "workflow", "approve"), {"confirm_token": preview.context["confirm_token"]}
        )

        assert response.status_code == 409
        obj.refresh_from_db()
        assert obj.status == RequestStatus.PENDING
        assert not obj.approved

    @parameterized.expand(
        [
            ("approve", RequestStatus.PENDING, "workflow", "approve"),
            ("retry", RequestStatus.FAILED, "workflow", "retry"),
            ("verify", RequestStatus.QUEUED, "workflow", "verify"),
            ("preview_stats", RequestStatus.DRAFT, "stats", "preview"),
        ]
    )
    def test_clickhouse_operations_need_the_clickhouse_team_group(
        self, _name: str, status: RequestStatus, panel: str, operation: str
    ) -> None:
        obj = self._request(status=status)
        self.user.groups.clear()

        with patch(f"{PANELS}.count_remaining_for_request", return_value=0) as counted:
            response = self.client.post(
                self._url(obj, panel, operation), {"reason": "Ticket 123", "execution_mode": "deferred"}
            )

        assert response.status_code == 403
        counted.assert_not_called()
        obj.refresh_from_db()
        assert obj.status == status

    def test_retry_requeues_a_failed_request_with_its_original_approval(self) -> None:
        approved_at = timezone.now() - timedelta(hours=2)
        obj = self._request(
            status=RequestStatus.FAILED, approved=True, approved_by=self.user, approved_at=approved_at, attempt_count=2
        )

        response = self.client.post(self._url(obj, "workflow", "retry"), {"reason": "Shard was down"})

        assert response.status_code == 302
        obj.refresh_from_db()
        assert (obj.status, obj.approved_by, obj.approved_at, obj.attempt_count) == (
            RequestStatus.APPROVED,
            self.user,
            approved_at,
            2,
        )

    @parameterized.expand([(status.value, status) for status in RequestStatus if status != RequestStatus.FAILED])
    def test_retry_is_only_offered_for_failed_requests(self, _name: str, status: RequestStatus) -> None:
        obj = self._request(status=status)

        response = self.client.post(self._url(obj, "workflow", "retry"), {"reason": "Shard was down"})

        assert response.status_code == 404
        obj.refresh_from_db()
        assert obj.status == status

    @parameterized.expand(
        [
            ("queued_and_gone", RequestStatus.QUEUED, 0, RequestStatus.COMPLETED),
            ("queued_with_rows_left", RequestStatus.QUEUED, 5, RequestStatus.QUEUED),
            ("approved_and_gone", RequestStatus.APPROVED, 0, RequestStatus.COMPLETED),
            ("failed_and_gone", RequestStatus.FAILED, 0, RequestStatus.COMPLETED),
            ("failed_with_rows_left", RequestStatus.FAILED, 3, RequestStatus.FAILED),
        ]
    )
    def test_verify_completes_a_request_once_no_rows_remain(
        self, _name: str, status: RequestStatus, remaining: int, expected: RequestStatus
    ) -> None:
        obj = self._request(status=status)

        with patch(f"{PANELS}.count_remaining_for_request", return_value=remaining):
            response = self.client.post(self._url(obj, "workflow", "verify"))

        assert response.status_code == 302
        obj.refresh_from_db()
        assert obj.status == expected

    def test_verify_does_not_complete_criteria_edited_while_it_counted(self) -> None:
        obj = self._request(status=RequestStatus.FAILED)

        def count_during_an_edit(request: DataDeletionRequest) -> int:
            DataDeletionRequest.objects.filter(pk=request.pk).update(criteria_updated_at=timezone.now())
            return 0

        with patch(f"{PANELS}.count_remaining_for_request", side_effect=count_during_an_edit):
            self.client.post(self._url(obj, "workflow", "verify"))

        obj.refresh_from_db()
        assert obj.status == RequestStatus.FAILED

    @parameterized.expand(
        [("person_removal", RequestType.PERSON_REMOVAL), ("query_backed", RequestType.HOGQL_EVENT_REMOVAL)]
    )
    def test_verify_is_not_offered_where_it_is_not_automated(self, _name: str, request_type: RequestType) -> None:
        obj = self._request(request_type=request_type, status=RequestStatus.FAILED)

        with patch(f"{PANELS}.count_remaining_for_request") as counted:
            response = self.client.post(self._url(obj, "workflow", "verify"))

        assert response.status_code == 404
        counted.assert_not_called()
        assert "Verify manually" in self.client.get(self._url(obj)).content.decode()

    @parameterized.expand([("fetch", True), ("preview", False)])
    def test_stats_of_a_person_removal_count_its_targets(self, operation: str, saved: bool) -> None:
        obj = self._request(
            request_type=RequestType.PERSON_REMOVAL,
            events=[],
            person_distinct_ids=["user-1", "user-2"],
            person_drop_profiles=True,
        )

        response = self.client.post(self._url(obj, "stats", operation), follow=True)

        assert "Selector count: 2 person targets" in response.content.decode()
        obj.refresh_from_db()
        assert (obj.count, obj.stats_calculated_at is not None) == ((2, True) if saved else (None, False))
