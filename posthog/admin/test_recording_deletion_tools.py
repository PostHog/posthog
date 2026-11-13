from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.session_replay.delete_recordings.staff import DeletionRun, RecordingDeletions


class TestRecordingDeletionTools(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    @parameterized.expand(
        [
            (
                "person_dry_run",
                "delete-by-person",
                {"distinct_ids": "user-1\n\nuser-2\n", "dry_run": "on"},
                None,
                "delete-recordings-with-person",
                {"distinct_ids": ["user-1", "user-2"]},
            ),
            (
                "filters_with_a_relative_date",
                "delete-by-filters",
                {"date_from": "-30d", "duration_max": "5", "platform": "web", "confirm_team_id": "{team_id}"},
                None,
                "delete-recordings-with-query",
                {
                    "query": {
                        "date_from": "-30d",
                        "having_predicates": '[{"type": "recording", "key": "duration", "operator": "lt", "value": 5}, '
                        '{"type": "recording", "key": "snapshot_source", "operator": "exact", "value": ["web"]}]',
                    }
                },
            ),
            (
                "filters_with_a_datetime_and_its_offset",
                "delete-by-filters",
                {"date_from": "2024-01-01T00:00:00+00:00", "date_to": "-7d", "dry_run": "on"},
                None,
                "delete-recordings-with-query",
                {"query": {"date_from": "2024-01-01T00:00:00+00:00", "date_to": "-7d"}},
            ),
            (
                "filters_without_a_date_from_name_the_query_default",
                "delete-by-filters",
                {"duration_max": "5", "dry_run": "on"},
                None,
                "delete-recordings-with-query",
                {
                    "query": {
                        "date_from": "-3d",
                        "having_predicates": '[{"type": "recording", "key": "duration", "operator": "lt", "value": 5}]',
                    }
                },
            ),
            (
                "filters_with_null_as_the_date",
                "delete-by-filters",
                {"date_from": "null", "dry_run": "on"},
                None,
                None,
                None,
            ),
            (
                "filters_with_a_bare_number_of_days",
                "delete-by-filters",
                {"date_from": "-30", "dry_run": "on"},
                None,
                None,
                None,
            ),
            ("filters_with_a_bare_year", "delete-by-filters", {"date_from": "2024", "dry_run": "on"}, None, None, None),
            (
                "filters_with_a_bare_year_and_month",
                "delete-by-filters",
                {"date_from": "202401", "dry_run": "on"},
                None,
                None,
                None,
            ),
            (
                "filters_with_non_ascii_digits_in_a_date",
                "delete-by-filters",
                {"date_to": "-\uff13\uff10d", "dry_run": "on"},
                None,
                None,
                None,
            ),
            (
                "filters_with_an_unsupported_date_unit",
                "delete-by-filters",
                {"date_to": "-30D", "dry_run": "on"},
                None,
                None,
                None,
            ),
            (
                "filters_with_a_date_unit_without_a_number",
                "delete-by-filters",
                {"date_to": "w", "dry_run": "on"},
                None,
                None,
                None,
            ),
            (
                "filters_with_a_date_that_is_not_one",
                "delete-by-filters",
                {"date_to": "yesterday", "dry_run": "on"},
                None,
                None,
                None,
            ),
            ("filters_without_a_filter", "delete-by-filters", {"dry_run": "on"}, None, None, None),
            (
                "filters_with_a_person_uuid",
                "delete-by-filters",
                {"person_uuid": " 6B1E2C3D-4F5A-4B6C-8D7E-9F0A1B2C3D4E ", "dry_run": "on"},
                None,
                "delete-recordings-with-query",
                {"query": {"date_from": "-3d", "person_uuid": "6b1e2c3d-4f5a-4b6c-8d7e-9f0a1b2c3d4e"}},
            ),
            ("filters_with_null_as_the_person", "delete-by-filters", {"person_uuid": "null"}, None, None, None),
            ("filters_with_quotes_as_the_person", "delete-by-filters", {"person_uuid": '""'}, None, None, None),
            ("all_without_the_typed_team_id", "delete-all", {"confirm_team_id": "0"}, None, None, None),
            (
                "all_with_the_typed_team_id",
                "delete-all",
                {"confirm_team_id": "{team_id}"},
                None,
                "delete-recordings-with-team",
                {},
            ),
            (
                "session_ids_from_a_csv",
                "delete-by-session-ids",
                {"dry_run": "on"},
                ("sessions.csv", b"session_id\nsession-a\nsession-b\nsession-a\n"),
                "delete-recordings-with-session-ids",
                {"total_session_ids": 2, "source_filename": "sessions.csv"},
            ),
            (
                "session_ids_from_an_excel_csv_with_a_byte_order_mark",
                "delete-by-session-ids",
                {"dry_run": "on"},
                ("sessions.csv", b"\xef\xbb\xbfsession_id\r\nsession-a\r\nsession-b\r\n"),
                "delete-recordings-with-session-ids",
                {"total_session_ids": 2},
            ),
            (
                "session_ids_from_a_csv_with_a_value_too_long_for_a_session_id",
                "delete-by-session-ids",
                {"dry_run": "on"},
                ("sessions.csv", b"a" * 140_000 + b"\n"),
                None,
                None,
            ),
            (
                "session_ids_from_a_file_that_is_not_csv",
                "delete-by-session-ids",
                {"dry_run": "on"},
                ("ids.txt", b"session-a"),
                None,
                None,
            ),
        ]
    )
    @patch("posthog.temporal.session_replay.delete_recordings.staff.store_session_id_chunks")
    @patch("posthog.temporal.session_replay.delete_recordings.staff.sync_connect")
    def test_recording_deletions_preview_then_start_the_workflow(
        self,
        _name: str,
        operation_key: str,
        data: dict[str, str],
        upload: tuple[str, bytes] | None,
        expected_workflow: str | None,
        expected_input: dict[str, object] | None,
        sync_connect: MagicMock,
        store_chunks: MagicMock,
    ) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        store_chunks.return_value = ("deletion-inputs/run/", 1)
        url = f"/admin/console/teams/{self.team.pk}/recordings/{operation_key}/"
        form: dict[str, object] = {
            key: value.format(team_id=self.team.pk) for key, value in {**data, "reason": "GDPR request"}.items()
        }
        if upload is not None:
            form["csv_file"] = SimpleUploadedFile(upload[0], upload[1], "text/csv")

        preview = self.client.post(url, form)
        if expected_workflow is None:
            assert preview.status_code == 400
            assert not sync_connect.return_value.start_workflow.called
            return
        assert preview.status_code == 200
        assert not sync_connect.return_value.start_workflow.called

        started = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert started.status_code == 302
        assert started["Location"].startswith(f"/admin/console/tools/recording-deletions/?team={self.team.pk}&started=")
        workflow, workflow_input = sync_connect.return_value.start_workflow.call_args.args
        assert workflow == expected_workflow
        assert workflow_input.team_id == self.team.pk
        assert workflow_input.config.reason == "GDPR request"
        assert workflow_input.config.deleted_by == self.user.email
        assert workflow_input.config.dry_run == ("dry_run" in data)
        for field, value in (expected_input or {}).items():
            actual = getattr(workflow_input, field)
            assert (dict(parse_qsl(actual)) if field == "query" else actual) == value
        if upload is not None:
            assert store_chunks.call_args.args[1] == ["session-a", "session-b"]

    @patch("posthog.temporal.session_replay.delete_recordings.staff.sync_connect")
    def test_a_real_run_after_a_dry_run_from_the_same_form_is_its_own_workflow(self, sync_connect: MagicMock) -> None:
        start_workflow = sync_connect.return_value.start_workflow = AsyncMock()
        url = f"/admin/console/teams/{self.team.pk}/recordings/delete-by-person/"
        nonce = "0b6c3c5e-6f5a-4a4e-9a51-3c3b2f1c9d10"

        def run(data: dict[str, str]) -> Any:
            form = {"distinct_ids": "user-1", "reason": "GDPR request", "form_nonce": nonce, **data}
            preview = self.client.post(url, form)
            return self.client.post(url, {"confirm_token": preview.context["confirm_token"], "form_nonce": nonce})

        run({"dry_run": "on"})
        run({})
        start_workflow.side_effect = WorkflowAlreadyStartedError("delete-recordings", "delete-recordings-with-person")
        repeated = run({})

        dry_run_id, real_id = (call.kwargs["id"] for call in start_workflow.call_args_list[:2])
        assert dry_run_id != real_id
        assert [call.args[1].config.dry_run for call in start_workflow.call_args_list[:2]] == [True, False]
        assert repeated.status_code == 302
        assert "started=" not in repeated["Location"]
        assert "No new deletion started" in " ".join(str(m) for m in get_messages(repeated.wsgi_request))

    @patch("posthog.temporal.session_replay.delete_recordings.staff.discard_session_id_chunks")
    @patch("posthog.temporal.session_replay.delete_recordings.staff.store_session_id_chunks")
    @patch("posthog.temporal.session_replay.delete_recordings.staff.sync_connect")
    def test_a_session_ids_start_that_temporal_refuses_discards_its_chunks(
        self, sync_connect: MagicMock, store_chunks: MagicMock, discard_chunks: MagicMock
    ) -> None:
        sync_connect.return_value.start_workflow = AsyncMock(
            side_effect=WorkflowAlreadyStartedError("delete-recordings", "delete-recordings-with-session-ids")
        )
        store_chunks.return_value = ("deletion-inputs/attempt/", 1)
        url = f"/admin/console/teams/{self.team.pk}/recordings/delete-by-session-ids/"
        form = {
            "dry_run": "on",
            "reason": "GDPR request",
            "csv_file": SimpleUploadedFile("sessions.csv", b"session-a\n", "text/csv"),
        }
        preview = self.client.post(url, form)

        repeated = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert repeated.status_code == 302
        discard_chunks.assert_called_once_with("deletion-inputs/attempt/", 1)

    @patch("posthog.temporal.session_replay.delete_recordings.staff.sync_connect")
    def test_a_confirm_whose_cached_upload_expired_starts_nothing(self, sync_connect: MagicMock) -> None:
        sync_connect.return_value.start_workflow = AsyncMock()
        url = f"/admin/console/teams/{self.team.pk}/recordings/delete-by-session-ids/"
        preview = self.client.post(
            url,
            {
                "dry_run": "on",
                "reason": "GDPR request",
                "csv_file": SimpleUploadedFile("sessions.csv", b"session-a\n", "text/csv"),
            },
        )
        cache.clear()

        confirmed = self.client.post(url, {"confirm_token": preview.context["confirm_token"]})

        assert confirmed.status_code == 302
        assert "expired" in " ".join(str(m) for m in get_messages(confirmed.wsgi_request))
        assert not sync_connect.return_value.start_workflow.called

    @parameterized.expand(
        [
            ("just_started", 10, True, "Starting"),
            ("pushed_off_the_recent_list", 600, False, "Not in the 20 most recent runs"),
        ]
    )
    @patch.object(RecordingDeletions, "recent", return_value=[])
    def test_the_runs_list_waits_for_a_started_run_only_for_a_while(
        self, _name: str, seconds_ago: int, refreshes: bool, expected_status: str, _recent: MagicMock
    ) -> None:
        workflow_id = f"delete-recordings-{self.team.pk}-0b6c3c5e-6f5a-4a4e-9a51-3c3b2f1c9d10"
        now = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)

        with time_machine.travel(now, tick=False):
            live = self.client.get(
                "/admin/console/tools/recording-deletions/live/runs/",
                {
                    "team": str(self.team.pk),
                    "started": workflow_id,
                    "started_at": str(int(now.timestamp()) - seconds_ago),
                },
            ).content.decode()

        assert ("data-refresh-seconds" in live) == refreshes
        assert expected_status in live
        assert f"/workflows/{workflow_id}" in live

    @patch.object(RecordingDeletions, "recent")
    @patch.object(RecordingDeletions, "certificate")
    def test_a_completed_recording_deletion_links_to_its_printable_certificate_and_json(
        self, certificate: MagicMock, recent: MagicMock
    ) -> None:
        workflow_id = f"delete-recordings-{self.team.pk}-0b6c3c5e-6f5a-4a4e-9a51-3c3b2f1c9d10"
        recent.return_value = [
            DeletionRun(
                workflow_id=workflow_id,
                run_id="run-1",
                workflow_type="delete-recordings-with-query",
                status="COMPLETED",
                started=datetime(2026, 11, 1, 10, 0, tzinfo=UTC),
                closed=datetime(2026, 11, 1, 10, 5, tzinfo=UTC),
            )
        ]
        certificate.return_value = (
            {
                "workflow_type": "query",
                "workflow_id": workflow_id,
                "team_id": self.team.pk,
                "dry_run": True,
                "reason": "GDPR request",
                "query": 'date_from=-30d&having_predicates=[{"key": "duration", "operator": "lt", "value": 5}]',
                "started_at": "2026-11-01T10:00:00+00:00",
                "completed_at": "2026-11-01T10:05:00+00:00",
                "total_recordings_found": 3,
                "total_deleted": 0,
                "total_failed": 0,
            },
            None,
        )
        certificate_url = f"/admin/posthog/team/{self.team.pk}/delete-recordings/certificate/{workflow_id}/"
        download_url = f"/admin/console/tools/recording-deletions/download/certificate/?team={self.team.pk}&certificate={workflow_id}"

        runs = self.client.get("/admin/console/tools/recording-deletions/", {"team": self.team.pk}).content.decode()
        printable = self.client.get(certificate_url)
        download = self.client.get(download_url)

        assert certificate_url in runs
        assert download_url.replace("&", "&amp;") in runs
        assert printable.status_code == 200
        content = printable.content.decode()
        assert "Certificate of Data Deletion" in content
        assert "Reference: 0b6c3c5e-6f5a-4a4e-9a51-3c3b2f1c9d10" in content
        assert "date from: -30d, duration &lt; 5s" in content
        assert f"/admin/console/tools/recording-deletions/?team={self.team.pk}" in content
        assert download.status_code == 200
        assert download["Content-Disposition"] == f'attachment; filename="deletion-certificate-{workflow_id}.json"'
        assert download.json()["total_recordings_found"] == 3
