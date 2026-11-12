import csv
import json
import time
import uuid
from dataclasses import replace
from typing import Any, cast
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

import structlog
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.schema import RecordingsQuery

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Download, Live, Notice, Page, Row, Table
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.session_replay.delete_recordings.staff import (
    RECENT_RUNS,
    DeletionRequest,
    DeletionRun,
    RecordingDeletions,
    RecordingFilters,
    describe_query,
    normalize_date_filter,
    session_ids_from_csv,
)

logger = structlog.get_logger(__name__)

RECORDINGS_QUERY_DEFAULT_DATE_FROM = RecordingsQuery.model_fields["date_from"].default
REPLAY = Owner(name="Replay", crest="replay")
TOOL_KEY = "recording-deletions"
TOOL_URL = f"/admin/console/tools/{TOOL_KEY}/"
PANEL_KEY = "recordings"
REFRESH_SECONDS_WHILE_RUNNING = 5
REFRESH_SECONDS_WHILE_TEMPORAL_IS_AWAY = 30
PREVIEW_SAMPLE_SIZE = 10
# A session ID takes about 37 bytes per CSV line, so the byte cap also bounds what the cache holds.
MAX_CSV_SESSION_IDS = 500_000
MAX_CSV_BYTES = 25_000_000
# Session IDs are UUIDs. The csv module's own field limit is process-wide, and other modules raise it.
MAX_SESSION_ID_LENGTH = 200
WAIT_FOR_NEW_RUN_SECONDS = 120
UNDO_HINT = "Deleted recordings cannot be restored. A dry run deletes nothing."
STATUS_TONES = {
    "RUNNING": Tone.INFO,
    "CONTINUED_AS_NEW": Tone.INFO,
    "COMPLETED": Tone.SUCCESS,
    "FAILED": Tone.DESTRUCTIVE,
    "TERMINATED": Tone.DESTRUCTIVE,
    "TIMED_OUT": Tone.DESTRUCTIVE,
    "CANCELED": Tone.WARNING,
}


class DeletionForm(forms.Form):
    dry_run = forms.BooleanField(
        required=False, initial=True, label="Dry run: count the recordings that match and delete nothing"
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log and the deletion certificate."
    )


class ConfirmTeamIdForm(DeletionForm):
    # These deletions cover more than staff can check by eye, so a real run needs the team ID typed out.
    confirm_team_id = forms.CharField(
        required=False,
        label="Team ID",
        help_text="Type the ID of this team, shown above, to delete for real. A dry run does not need it.",
    )
    field_order = ["dry_run", "confirm_team_id", "reason"]


class PersonDeletionForm(DeletionForm):
    distinct_ids = forms.CharField(widget=forms.Textarea, label="Distinct IDs", help_text="One per line.")
    field_order = ["distinct_ids", "dry_run", "reason"]

    def clean_distinct_ids(self) -> list[str]:
        distinct_ids = [line.strip() for line in self.cleaned_data["distinct_ids"].splitlines() if line.strip()]
        if not distinct_ids:
            raise forms.ValidationError("Enter at least one distinct ID.")
        return distinct_ids


def _clean_date(value: str) -> str:
    if not value.strip():
        return ""
    try:
        return normalize_date_filter(value)
    except ValueError:
        raise forms.ValidationError("Enter a relative date, such as -30d, or a date, such as 2024-01-01.")


class FilterDeletionForm(ConfirmTeamIdForm):
    date_from = forms.CharField(
        required=False,
        help_text=(
            "Relative, such as -30d, or a date, such as 2024-01-01. Leave empty for the last 3 days, which is "
            "what the recordings query uses then."
        ),
    )
    date_to = forms.CharField(required=False, help_text="Leave empty for now.")
    duration_min = forms.IntegerField(required=False, min_value=0, label="Min duration (seconds)")
    duration_max = forms.IntegerField(
        required=False, min_value=0, label="Max duration (seconds)", help_text="Short sessions are often bots."
    )
    person_uuid = forms.UUIDField(required=False, label="Person UUID")
    platform = forms.ChoiceField(required=False, choices=[("", "Any platform"), ("web", "Web"), ("mobile", "Mobile")])
    field_order = [
        "date_from",
        "date_to",
        "duration_min",
        "duration_max",
        "person_uuid",
        "platform",
        "dry_run",
        "confirm_team_id",
        "reason",
    ]

    def clean_date_from(self) -> str:
        return _clean_date(self.cleaned_data["date_from"])

    def clean_date_to(self) -> str:
        return _clean_date(self.cleaned_data["date_to"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if not self.errors and self._entered_filters().is_empty():
            raise forms.ValidationError("Set at least one filter.")
        return cleaned

    def filters(self) -> RecordingFilters:
        # The recordings query starts at its own default without a date from, so the preview and the certificate
        # name that start instead of reading as all time.
        entered = self._entered_filters()
        return replace(entered, date_from=entered.date_from or RECORDINGS_QUERY_DEFAULT_DATE_FROM)

    def _entered_filters(self) -> RecordingFilters:
        return RecordingFilters(
            date_from=self.cleaned_data.get("date_from", ""),
            date_to=self.cleaned_data.get("date_to", ""),
            duration_min=self.cleaned_data.get("duration_min"),
            duration_max=self.cleaned_data.get("duration_max"),
            person_uuid=str(self.cleaned_data["person_uuid"]) if self.cleaned_data.get("person_uuid") else "",
            platform=self.cleaned_data.get("platform", ""),
        )


class SessionIdsDeletionForm(DeletionForm):
    csv_file = forms.FileField(
        label="CSV file",
        widget=forms.FileInput(attrs={"accept": ".csv"}),
        help_text="Session IDs in the first column. A session_id header row is skipped.",
    )
    field_order = ["csv_file", "dry_run", "reason"]

    def clean_csv_file(self) -> list[str]:
        upload = self.cleaned_data["csv_file"]
        if not (upload.name or "").endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file.")
        # The preview keeps the file in the cache until staff confirm, so the size is checked before that.
        if upload.size > MAX_CSV_BYTES:
            raise forms.ValidationError(
                f"The file is larger than {MAX_CSV_BYTES // 1_000_000} MB. Split it and upload each part on its own."
            )
        try:
            # Excel starts a UTF-8 CSV with a byte order mark, which would otherwise end up in the first session ID.
            content = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise forms.ValidationError("The file is not UTF-8 text. Save it as a UTF-8 CSV and upload it again.")
        try:
            session_ids = session_ids_from_csv(content)
        except csv.Error:
            raise forms.ValidationError(
                "The file could not be read as a CSV. Check that it holds one session ID per line and upload it again."
            )
        if not session_ids:
            raise forms.ValidationError("The file holds no session IDs.")
        too_long = next((session_id for session_id in session_ids if len(session_id) > MAX_SESSION_ID_LENGTH), None)
        if too_long is not None:
            raise forms.ValidationError(
                f"The file holds a value of {len(too_long):,} characters, which is not a session ID. "
                "Check that the first column holds only session IDs."
            )
        if len(session_ids) > MAX_CSV_SESSION_IDS:
            raise forms.ValidationError(
                f"The file holds {len(session_ids):,} session IDs. Upload at most {MAX_CSV_SESSION_IDS:,} at a time."
            )
        self.cleaned_data["source_filename"] = upload.name
        return session_ids


def _form_nonce(request: HttpRequest) -> uuid.UUID:
    # The browser sends the nonce, so anything that is not a UUID gets a fresh one.
    try:
        return uuid.UUID(request.POST.get("form_nonce", ""))
    except ValueError:
        return uuid.uuid4()


def recording_deletions_url(team: Team, **params: str) -> str:
    return f"{TOOL_URL}?{urlencode({'team': team.pk, **params})}"


def _deletion_request(request: HttpRequest, team: Team, form: forms.Form, kind: str, scope: str) -> DeletionRequest:
    dry_run = form.cleaned_data["dry_run"]
    return DeletionRequest(
        team=team,
        workflow_id=RecordingDeletions.workflow_id(team.pk, _form_nonce(request), kind, dry_run, scope),
        reason=form.cleaned_data["reason"],
        dry_run=dry_run,
        requested_by=cast(User, request.user),
    )


def _typed_team_id_matches(team: Team, form: forms.Form) -> bool:
    return form.cleaned_data["dry_run"] or form.cleaned_data["confirm_team_id"].strip() == str(team.pk)


class StartDeletion:
    """Runs one kind of deletion, then sends staff to the team's runs, where the new run shows up."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def __call__(self, request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
        assert isinstance(obj, Team) and form is not None
        if "confirm_team_id" in form.fields and not _typed_team_id_matches(obj, form):
            messages.error(request, f"Type {obj.pk}, the ID of this team, to delete its recordings.")
            return HttpResponse(status=400)
        try:
            if self.kind == "person":
                distinct_ids = form.cleaned_data["distinct_ids"]
                deletion = _deletion_request(request, obj, form, self.kind, "\n".join(distinct_ids))
                RecordingDeletions.start_for_person(deletion, distinct_ids)
            elif self.kind == "team":
                deletion = _deletion_request(request, obj, form, self.kind, "")
                RecordingDeletions.start_for_team(deletion)
            elif self.kind == "filters":
                assert isinstance(form, FilterDeletionForm)
                filters = form.filters()
                deletion = _deletion_request(request, obj, form, self.kind, filters.query())
                RecordingDeletions.start_for_filters(deletion, filters)
            else:
                session_ids = form.cleaned_data["csv_file"]
                deletion = _deletion_request(request, obj, form, self.kind, "\n".join(session_ids))
                RecordingDeletions.start_for_session_ids(deletion, session_ids, form.cleaned_data["source_filename"])
        except WorkflowAlreadyStartedError:
            messages.warning(
                request,
                "No new deletion started. This form already started this exact deletion, which shows in the list below.",
            )
            return HttpResponseRedirect(recording_deletions_url(obj))
        except Exception:
            logger.exception("admin_console_recording_deletion_failed", team_id=obj.pk, kind=self.kind)
            messages.error(request, "Could not start the deletion. Check the server logs for details.")
            return HttpResponse(status=502)
        dry_run = " as a dry run" if deletion.dry_run else ""
        messages.success(request, f"Started {deletion.workflow_id}{dry_run}.")
        # Temporal lists a new run only after a moment, so the page names it and refreshes until it shows or the wait ends.
        return HttpResponseRedirect(
            recording_deletions_url(obj, started=deletion.workflow_id, started_at=str(int(time.time())))
        )


class PreviewDeletion:
    """Shows the scope of a deletion before it starts. The exact recordings are known only once a run counts them."""

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def __call__(self, request: HttpRequest, obj: Model, form: forms.Form) -> Page:
        assert isinstance(obj, Team)
        if "confirm_team_id" in form.fields and not _typed_team_id_matches(obj, form):
            form.add_error("confirm_team_id", f"Type {obj.pk}, the ID of this team, to delete for real.")
        dry_run = form.cleaned_data["dry_run"]
        notice = (
            "Dry run: nothing is deleted. The run counts the recordings that match, and its certificate says it was a dry run."
            if dry_run
            else f"This permanently deletes the recordings below from {obj.name} ({obj.pk}). It cannot be undone."
        )
        rows = [
            Row(cells=(Cell(text="Team"), Cell(text=f"{obj.name} ({obj.pk})"))),
            *self._scope_rows(obj, form),
            Row(
                cells=(
                    Cell(text="Dry run"),
                    Cell(text="Yes" if dry_run else "No", tone=None if dry_run else Tone.DESTRUCTIVE),
                )
            ),
            Row(cells=(Cell(text="Reason"), Cell(text=form.cleaned_data["reason"]))),
        ]
        return Page(blocks=(Notice(text=notice), Table(columns=("What", "Value"), rows=tuple(rows))))

    def _scope_rows(self, team: Team, form: forms.Form) -> list[Row]:
        if self.kind == "person":
            distinct_ids: list[str] = form.cleaned_data["distinct_ids"]
            return [
                Row(cells=(Cell(text="Recordings of"), Cell(text=f"{len(distinct_ids):,} distinct IDs"))),
                Row(cells=(Cell(text="Distinct IDs"), Cell(text=_sample(distinct_ids), mono=True))),
            ]
        if self.kind == "team":
            return [Row(cells=(Cell(text="Recordings"), Cell(text="Every recording of this team", tone=Tone.WARNING)))]
        if self.kind == "filters":
            assert isinstance(form, FilterDeletionForm)
            return [Row(cells=(Cell(text="Recordings matching"), Cell(text=describe_query(form.filters().query()))))]
        session_ids: list[str] = form.cleaned_data["csv_file"]
        return [
            Row(cells=(Cell(text="File"), Cell(text=form.cleaned_data["source_filename"]))),
            Row(cells=(Cell(text="Session IDs"), Cell(text=f"{len(session_ids):,}"))),
            Row(cells=(Cell(text="First session IDs"), Cell(text=_sample(session_ids), mono=True))),
        ]


def _sample(values: list[str]) -> str:
    shown = ", ".join(values[:PREVIEW_SAMPLE_SIZE])
    hidden = len(values) - PREVIEW_SAMPLE_SIZE
    return f"{shown}, and {hidden:,} more" if hidden > 0 else shown


def _operation(kind: str, key: str, label: str, description: str, form_class: type[forms.Form]) -> Operation:
    return Operation(
        key=key,
        label=label,
        handler=StartDeletion(kind),
        danger=True,
        description=description,
        form_class=form_class,
        undo_hint=UNDO_HINT,
        preview=PreviewDeletion(kind),
    )


@console.register_panel
class SessionRecordingsPanel(Panel):
    record = "team"
    key = PANEL_KEY
    title = "Session recordings"
    owner = REPLAY
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        return [Fact(label="Deletions", value="Runs and deletion certificates", href=recording_deletions_url(obj))]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            _operation(
                "person",
                "delete-by-person",
                "Delete recordings of persons",
                "Deletes every recording of the distinct IDs you list.",
                PersonDeletionForm,
            ),
            _operation(
                "filters",
                "delete-by-filters",
                "Delete recordings by filters",
                "Deletes the recordings that match the filters you set.",
                FilterDeletionForm,
            ),
            _operation(
                "session_ids",
                "delete-by-session-ids",
                "Delete recordings by session IDs",
                "Deletes the recordings whose session IDs are in a CSV file.",
                SessionIdsDeletionForm,
            ),
            _operation(
                "team",
                "delete-all",
                "Delete all recordings",
                "Deletes every recording of this team.",
                ConfirmTeamIdForm,
            ),
        ]


def _temporal_url(workflow_id: str, run_id: str = "") -> str:
    url = f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/workflows/{workflow_id}"
    return f"{url}/{run_id}" if run_id else url


def _unlisted_run_row(workflow_id: str, waiting: bool) -> Row:
    status = "Starting" if waiting else f"Not in the {RECENT_RUNS} most recent runs. Open it in Temporal."
    return Row(
        cells=(
            Cell(text=workflow_id, href=_temporal_url(workflow_id), mono=True),
            Cell(text="-", muted=True),
            Cell(text=status, tone=Tone.INFO if waiting else Tone.WARNING),
            *(Cell(text="-", muted=True) for _ in range(4)),
        )
    )


def _seconds_since(started_at: str) -> float | None:
    try:
        return time.time() - int(started_at)
    except ValueError:
        return None


def _run_row(team: Team, run: DeletionRun) -> Row:
    temporal_url = _temporal_url(run.workflow_id, run.run_id)
    completed = run.status == "COMPLETED"
    certificate_url = reverse("admin:posthog_team_deletion_certificate", args=[team.pk, run.workflow_id])
    download_url = reverse("admin_console_tool_download", kwargs={"tool_key": TOOL_KEY, "download_key": "certificate"})
    query = urlencode({"team": team.pk, "certificate": run.workflow_id})
    certificate = Cell(text="View", href=certificate_url) if completed else Cell(text="-", muted=True)
    download = Cell(text="JSON", href=f"{download_url}?{query}") if completed else Cell(text="-", muted=True)
    return Row(
        cells=(
            Cell(text=run.workflow_id, href=temporal_url, mono=True),
            Cell(text=run.workflow_type),
            Cell(text=run.status.replace("_", " ").capitalize(), tone=STATUS_TONES.get(run.status)),
            Cell(text=run.started.strftime("%Y-%m-%d %H:%M:%S") if run.started else "-", muted=run.started is None),
            Cell(text=run.closed.strftime("%Y-%m-%d %H:%M:%S") if run.closed else "-", muted=run.closed is None),
            certificate,
            download,
        )
    )


@console.register_tool
class RecordingDeletionsTool(ConsoleTool):
    key = TOOL_KEY
    title = "Recording deletions"
    owner = REPLAY
    group = "Data"
    description = "The recording deletions of one team, followed in Temporal, and their deletion certificates."

    def _team(self, request: HttpRequest) -> Team | None:
        team_id = request.GET.get("team", "").strip()
        if not (team_id.isascii() and team_id.isdigit()):
            return None
        return Team.objects.select_related("organization").filter(pk=int(team_id)).first()

    def page(self, request: HttpRequest) -> Page:
        team = self._team(request)
        if team is None:
            return Page(
                blocks=(
                    Notice(
                        text="Open this page from the Session recordings panel on a team page.",
                        link_text="Find a team",
                        href="/admin/console/",
                    ),
                )
            )
        runs = self.live(request, "runs")
        assert runs is not None
        team_url = reverse("admin_console_team", kwargs={"pk": team.pk})
        return Page(
            blocks=(
                Notice(
                    text=f"Deletions of {team.name} ({team.pk}).",
                    link_text="Back to the team",
                    href=f"{team_url}#panel-{PANEL_KEY}",
                ),
                runs,
            )
        )

    def live(self, request: HttpRequest, key: str) -> Live | None:
        team = self._team(request)
        if key != "runs" or team is None:
            return None
        runs = RecordingDeletions.recent(team.pk)
        if runs is None:
            return Live(
                key="runs",
                block=Notice(text="Temporal did not answer, so the runs cannot be shown. This retries on its own."),
                refresh_seconds=REFRESH_SECONDS_WHILE_TEMPORAL_IS_AWAY,
            )
        rows = [_run_row(team, run) for run in runs]
        running = any(run.status in ("RUNNING", "CONTINUED_AS_NEW") for run in runs)
        started = request.GET.get("started")
        waiting_for_new_run = False
        listed = {run.workflow_id for run in runs}
        if started and started.startswith(f"delete-recordings-{team.pk}-") and started not in listed:
            seconds_since_start = _seconds_since(request.GET.get("started_at", ""))
            waiting_for_new_run = (
                seconds_since_start is not None and 0 <= seconds_since_start < WAIT_FOR_NEW_RUN_SECONDS
            )
            rows.insert(0, _unlisted_run_row(started, waiting_for_new_run))
        return Live(
            key="runs",
            block=Table(
                columns=("Workflow", "Type", "Status", "Started", "Finished", "Certificate", "Download"),
                rows=tuple(rows),
                empty_text="No deletions have run for this team yet.",
            ),
            refresh_seconds=REFRESH_SECONDS_WHILE_RUNNING if running or waiting_for_new_run else None,
        )

    def download(self, request: HttpRequest, key: str) -> Download | None:
        team = self._team(request)
        workflow_id = request.GET.get("certificate", "")
        if key != "certificate" or team is None or not workflow_id:
            return None
        certificate, _error = RecordingDeletions.certificate(team.pk, workflow_id)
        if certificate is None:
            return None
        return Download(
            filename=f"deletion-certificate-{workflow_id}.json",
            content_type="application/json",
            content=json.dumps(certificate, indent=2, default=str),
        )


# Old Django admin URLs of the recording deletion pages. Staff keep bookmarks to them, query parameters included.
console.register_moved_action(
    old_path="admin/posthog/team/<int:pk>/delete-recordings/", record="team", target="#panel-recordings"
)
console.register_moved_page(
    old_path="admin/posthog/team/<int:pk>/delete-recordings/workflows/",
    title="Recording deletion runs",
    url="/admin/console/tools/recording-deletions/?team={pk}",
)
