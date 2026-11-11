from datetime import timedelta
from typing import cast

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django import forms
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from bs4 import BeautifulSoup
from parameterized import parameterized

from posthog.admin.console.deletion_request_form import ArrayTextareaField, DataDeletionRequestForm
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL
from posthog.admin.console.registry import console
from posthog.models.data_deletion_request import (
    EDITABLE_STATUSES,
    AdhocEventDeletionBacklog,
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
)

PANELS = "posthog.admin.console.deletion_request_panels"
CREATE_URL = "/admin/console/tools/new-deletion-request/create/"


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

    def _edit(self, obj: DataDeletionRequest, data: dict[str, str]):
        # The form carries the revision it was opened at; tests open it at the request's current one.
        obj.refresh_from_db()
        return self.client.post(self._url(obj, "criteria", "edit"), {"revision": obj.updated_at.isoformat(), **data})

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
        for title in (
            "Overview",
            "ClickHouse stats",
            "Criteria",
            "Workflow",
            "Retry deletion",
            "Duplicate as a new draft",
        ):
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

    @parameterized.expand(
        [
            ("event_removal_with_notes", RequestType.EVENT_REMOVAL, "Support ticket #12345", "Support ticket #12345"),
            (
                "property_removal_with_notes",
                RequestType.PROPERTY_REMOVAL,
                "Support ticket #12345",
                "Support ticket #12345",
            ),
            ("blank_notes", RequestType.EVENT_REMOVAL, "  ", ""),
        ]
    )
    def test_submit_form_starts_with_the_notes_as_reason(
        self, _name: str, request_type: RequestType, notes: str, expected_reason: str
    ) -> None:
        obj = self._request(
            request_type=request_type, notes=notes, properties=["$ip"] if request_type != "event_removal" else []
        )

        response = self.client.get(self._url(obj, "workflow", "submit"))

        assert response.status_code == 200
        reason = BeautifulSoup(response.content, "html.parser").find("textarea", attrs={"name": "reason"})
        assert reason is not None
        assert reason.get_text().strip() == expected_reason

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
            opened = self.client.get(self._url(obj, panel, operation))
            response = self.client.post(
                self._url(obj, panel, operation), {"reason": "Ticket 123", "execution_mode": "deferred"}
            )

        assert (opened.status_code, response.status_code) == (403, 403)
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

    def _create(self, **data):
        fields = {
            "team_id": str(self.team.pk),
            "request_type": RequestType.EVENT_REMOVAL.value,
            "start_time": "2026-11-01 00:00",
            "end_time": "2026-11-02 00:00",
            "events": "$pageview\n$autocapture",
            "properties": "$ip",
            "notes": "Ticket 123",
        }
        return self.client.post(CREATE_URL, {**fields, **data})

    def test_create_makes_a_draft_and_opens_it(self) -> None:
        response = self._create()

        obj = DataDeletionRequest.objects.get()
        assert response.status_code == 302
        assert response["Location"] == self._url(obj)
        assert (obj.status, obj.events, obj.properties, obj.created_by, obj.created_by_staff) == (
            RequestStatus.DRAFT,
            ["$pageview", "$autocapture"],
            [],
            self.user,
            True,
        )
        assert LogEntry.objects.filter(object_id=str(obj.pk), action_flag=ADDITION).exists()

    @parameterized.expand([("member", True, 302), ("outside_clickhouse_team", False, 400)])
    def test_property_removal_is_only_created_by_the_clickhouse_team(
        self, _name: str, in_clickhouse_team: bool, expected: int
    ) -> None:
        if not in_clickhouse_team:
            self.user.groups.clear()

        response = self._create(request_type=RequestType.PROPERTY_REMOVAL.value)

        assert response.status_code == expected
        assert DataDeletionRequest.objects.exists() == in_clickhouse_team

    @parameterized.expand(
        [
            ("naive", "2025-01-08 08:12:00", "2025-01-08 08:12:00"),
            ("iso_utc", "2025-01-08T08:12:00Z", "2025-01-08 08:12:00"),
            ("other_offset", "2025-01-08T10:12:00+02:00", "2025-01-08 08:12:00"),
            ("unparseable", "next tuesday", ""),
            ("invalid_date", "2025-13-45 08:12:00", ""),
        ]
    )
    def test_create_form_is_prefilled_from_the_link(self, _name: str, start_time: str, expected: str) -> None:
        response = self.client.get(CREATE_URL, {"team_id": "42", "events": "$pageview", "start_time": start_time})

        assert response.status_code == 200
        soup = BeautifulSoup(response.content, "html.parser")
        assert soup.select_one("input[name=team_id]")["value"] == "42"
        assert soup.select_one("textarea[name=events]").get_text() == "$pageview"
        assert soup.select_one("input[name=start_time]")["value"] == expected

    def test_the_old_django_admin_add_link_opens_the_create_form_with_its_values(self) -> None:
        response = self.client.get("/admin/posthog/datadeletionrequest/add/?team_id=42&events=%24pageview")

        assert response.status_code == 302
        assert response["Location"] == f"{CREATE_URL}?team_id=42&events=%24pageview"

    def test_editing_the_criteria_of_a_pending_request_moves_it_back_to_draft(self) -> None:
        obj = self._request(status=RequestStatus.PENDING, count=10, stats_calculated_at=timezone.now())

        page = self.client.get(self._url(obj, "criteria", "edit"))
        response = self._edit(
            obj,
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": "2026-10-30 12:00",
                "end_time": "2026-11-06 11:59",
                "events": "$autocapture",
            },
        )

        assert "$pageview" in BeautifulSoup(page.content, "html.parser").select_one("textarea[name=events]").get_text()
        assert response.status_code == 302
        obj.refresh_from_db()
        assert (obj.status, obj.events, obj.count, obj.stats_calculated_at, obj.criteria_updated_by) == (
            RequestStatus.DRAFT,
            ["$autocapture"],
            None,
            None,
            self.user,
        )
        assert LogEntry.objects.filter(object_id=str(obj.pk), change_message__contains='"events"').exists()

    def test_editing_only_the_notes_keeps_a_pending_request_and_its_stats(self) -> None:
        obj = self._request(status=RequestStatus.PENDING, count=10)

        response = self._edit(
            obj,
            {
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": "2026-10-30 12:00",
                "end_time": "2026-11-06 11:59",
                "events": "$pageview",
                "notes": "More context",
            },
        )

        assert response.status_code == 302
        obj.refresh_from_db()
        assert (obj.status, obj.count, obj.notes) == (RequestStatus.PENDING, 10, "More context")

    def test_staff_outside_the_clickhouse_team_cannot_switch_to_property_removal(self) -> None:
        obj = self._request()
        self.user.groups.clear()

        response = self._edit(
            obj,
            {
                "request_type": RequestType.PROPERTY_REMOVAL.value,
                "start_time": "2026-10-30 12:00",
                "end_time": "2026-11-06 11:59",
                "events": "$pageview",
                "properties": "$ip",
            },
        )

        assert response.status_code == 400
        assert "Only members of the ClickHouse Team group can pick this type" in response.content.decode()
        obj.refresh_from_db()
        assert obj.request_type == RequestType.EVENT_REMOVAL

    def test_an_edit_does_not_overwrite_a_change_made_after_the_form_opened(self) -> None:
        obj = self._request(status=RequestStatus.PENDING)
        opened_at = obj.updated_at.isoformat()
        with time_machine.travel("2026-11-06T12:05:00Z", tick=False):
            DataDeletionRequest.objects.filter(pk=obj.pk).update(events=["$autocapture"], updated_at=timezone.now())

        response = self.client.post(
            self._url(obj, "criteria", "edit"),
            {
                "revision": opened_at,
                "request_type": RequestType.EVENT_REMOVAL.value,
                "start_time": "2026-10-30 12:00",
                "end_time": "2026-11-06 11:59",
                "events": "$pageview",
                "notes": "From a stale form",
            },
        )

        assert response.status_code == 409
        obj.refresh_from_db()
        assert (obj.events, obj.notes) == (["$autocapture"], "")

    @parameterized.expand(
        [
            ("property_removal", {"request_type": RequestType.PROPERTY_REMOVAL, "properties": ["$ip"]}),
            (
                "person_removal",
                {"request_type": RequestType.PERSON_REMOVAL, "person_distinct_ids": ["user-1"], "events": []},
            ),
        ]
    )
    def test_staff_outside_the_clickhouse_team_cannot_duplicate_a_type_they_cannot_create(
        self, _name: str, fields: dict
    ) -> None:
        obj = self._request(**fields)
        self.user.groups.clear()

        response = self.client.post(self._url(obj, "criteria", "duplicate"))

        assert response.status_code == 403
        assert DataDeletionRequest.objects.count() == 1

    @parameterized.expand([(status.value, status) for status in RequestStatus if status not in EDITABLE_STATUSES])
    def test_criteria_of_an_approved_or_later_request_cannot_be_edited(self, _name: str, status: RequestStatus) -> None:
        obj = self._request(status=status)

        response = self._edit(obj, {"events": "$autocapture"})

        assert response.status_code == 404
        obj.refresh_from_db()
        assert obj.events == ["$pageview"]

    @parameterized.expand(
        [
            ("with_notes", RequestType.EVENT_REMOVAL, "please be careful"),
            ("query_backed", RequestType.HOGQL_EVENT_REMOVAL, ""),
        ]
    )
    def test_duplicate_copies_the_criteria_into_a_new_draft(
        self, _name: str, request_type: RequestType, notes: str
    ) -> None:
        if request_type == RequestType.HOGQL_EVENT_REMOVAL:
            original = self._request(
                request_type=request_type,
                events=[],
                start_time=None,
                end_time=None,
                hogql_query="SELECT uuid FROM events WHERE event = {event}",
                hogql_variables={"event": "$pageview"},
                execution_mode=ExecutionMode.DEFERRED,
                status=RequestStatus.COMPLETED,
            )
        else:
            original = self._request(
                notes=notes, status=RequestStatus.COMPLETED, count=42, approved=True, attempt_count=3
            )

        response = self.client.post(self._url(original, "criteria", "duplicate"))

        copy = DataDeletionRequest.objects.exclude(pk=original.pk).get()
        assert response["Location"] == self._url(copy)
        assert (copy.team_id, copy.events, copy.hogql_query, copy.hogql_variables, copy.execution_mode) == (
            original.team_id,
            original.events,
            original.hogql_query,
            original.hogql_variables,
            original.execution_mode,
        )
        assert (copy.status, copy.count, copy.approved, copy.attempt_count, copy.created_by) == (
            RequestStatus.DRAFT,
            None,
            False,
            0,
            self.user,
        )
        assert copy.notes.startswith(
            f"Copy of data deletion request {original.pk} (http://testserver{self._url(original)})."
        )
        assert copy.notes.endswith(notes or ").")


class TestDeletionRequestForm(SimpleTestCase):
    @staticmethod
    def _type_values(form: DataDeletionRequestForm) -> list[str]:
        request_type = form.fields["request_type"]
        assert isinstance(request_type, forms.ChoiceField)
        return [value for value, _ in cast("list[tuple[str, str]]", request_type.choices)]

    @parameterized.expand(
        [
            ("outside_clickhouse_team", False, [RequestType.EVENT_REMOVAL]),
            ("clickhouse_team", True, [RequestType.PROPERTY_REMOVAL, RequestType.EVENT_REMOVAL]),
        ]
    )
    def test_types_offered_on_a_new_request(self, _name: str, member: bool, expected: list[RequestType]) -> None:
        assert self._type_values(DataDeletionRequestForm.for_staff(member)()) == expected

    @parameterized.expand([(RequestType.HOGQL_EVENT_REMOVAL,), (RequestType.PERSON_REMOVAL,)])
    def test_an_existing_request_keeps_its_own_type_selectable(self, request_type: RequestType) -> None:
        obj = DataDeletionRequest(team_id=1, request_type=request_type)
        obj._state.adding = False

        form = DataDeletionRequestForm.for_request(obj)()

        assert request_type in self._type_values(form)
        assert "team_id" not in form.fields

    @parameterized.expand(
        [
            ("one_per_line", "a\n b \n\n", ["a", "b"]),
            ("json_list", '["a", "b"]', ["a", "b"]),
            ("python_list", "['a', 'b']", ["a", "b"]),
            ("empty", "", []),
        ]
    )
    def test_list_fields_parse_what_staff_paste(self, _name: str, text: str, expected: list[str]) -> None:
        assert ArrayTextareaField(required=False).clean(text) == expected
