"""PostHog Admin for agent transcripts: the review queue, and a panel on each organization's page."""

import math
from datetime import datetime
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.defaultfilters import filesizeformat
from django.urls import reverse

from posthog.admin.console.panels import Fact, Handoff, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, FieldGroup, Filters, Notice, Page, Paging, Row, Table

from products.agent_transcripts.backend.facade import api
from products.agent_transcripts.backend.facade.contracts import (
    MERCH_CODE_MAX_LENGTH,
    MERCH_CODE_VALUE_USD,
    TRANSCRIPT_RETENTION_DAYS,
    AgentTranscriptSubmission,
    DuplicateMerchCode,
    InvalidSubmissionState,
    SubmissionForReview,
    SubmissionNotFound,
    Submitter,
    TranscriptStorageUnavailable,
)
from products.agent_transcripts.backend.facade.enums import SubmissionStatus

GROWTH = Owner(name="Growth", crest="growth")

# Hoglog viewer (github.com/PostHog/hoglog-viewer) reads agent logs in the browser. It accepts a handoff only from
# these origins, so a new region or domain needs adding to both lists.
HOGLOG_VIEWER = Handoff(url="https://hoglog-viewer.hosthog.dev/#handoff", tool="Hoglog viewer")
HOGLOG_VIEWER_OPENERS = frozenset({"https://us.posthog.com", "https://eu.posthog.com", "http://localhost:8010"})

QUEUE_TOOL_KEY = "agent-transcripts"
PANEL_KEY = "agent-transcript"
SUBMISSIONS_PER_PAGE = 50
DEFAULT_QUEUE_STATUS = SubmissionStatus.SUBMITTED
ANY_STATUS = "any"

DOWNLOAD_OPERATION = "download"
OPEN_IN_VIEWER_OPERATION = "open-in-viewer"
APPROVE_OPERATION = "approve"
REQUEST_CHANGES_OPERATION = "request-changes"
DECLINE_OPERATION = "decline"
DELETE_FILE_OPERATION = "delete-file"

STATUS_TONES: dict[SubmissionStatus, Tone | None] = {
    SubmissionStatus.PENDING_UPLOAD: None,
    SubmissionStatus.SUBMITTED: Tone.WARNING,
    SubmissionStatus.CHANGES_REQUESTED: Tone.INFO,
    SubmissionStatus.APPROVED: Tone.SUCCESS,
    SubmissionStatus.DECLINED: Tone.DESTRUCTIVE,
}

INTERNAL_NOTE_LABEL = "Internal note"
INTERNAL_NOTE_HELP = "Saved on the submission and in the audit log. The customer never sees it."
CUSTOMER_MESSAGE_LABEL = "Message to the customer"
NOT_IN_REVIEW_MESSAGE = "This transcript is no longer waiting for review. The page shows its current status."
FILE_GONE_MESSAGE = (
    f"The transcript file is gone. Staff deleted it, or it expired {TRANSCRIPT_RETENTION_DAYS} days after upload."
)


def _date(value: datetime | None) -> str:
    return value.strftime("%b %-d, %Y") if value else "-"


def _organization_url(organization_id: UUID) -> str:
    return reverse(RECORD_TYPES["organization"].url_name, kwargs={"pk": organization_id})


def _file_state(submission: AgentTranscriptSubmission) -> tuple[str, Tone | None]:
    if submission.file_deleted_at is not None:
        return "Deleted", None
    if submission.file_available:
        return "Available", Tone.SUCCESS
    if submission.submitted_at is None:
        return "Not uploaded", None
    return "Expired", None


def _stored_file_text(submission: AgentTranscriptSubmission) -> str:
    if submission.file_deleted_at is not None:
        return f"Deleted by staff on {_date(submission.file_deleted_at)}"
    if submission.file_available:
        return f"Deleted automatically on {_date(submission.file_expires_at)}"
    return f"Expired on {_date(submission.file_expires_at)}"


def _submitter_text(submitter: Submitter | None) -> str:
    if submitter is None:
        return "A deleted user"
    if submitter.name:
        return f"{submitter.name} ({submitter.email})"
    return submitter.email


class QueueFilterForm(forms.Form):
    status = forms.ChoiceField(
        label="Status",
        choices=[*SubmissionStatus.choices, (ANY_STATUS, "Any status")],
        initial=DEFAULT_QUEUE_STATUS.value,
    )


def _selected_status(form: QueueFilterForm) -> SubmissionStatus | None:
    value = form.cleaned_data["status"] if form.is_bound and form.is_valid() else DEFAULT_QUEUE_STATUS.value
    return None if value == ANY_STATUS else SubmissionStatus(value)


def _page_number(request: HttpRequest) -> int:
    try:
        return max(1, int(request.GET.get("page", "1")))
    except ValueError:
        return 1


def _queue_row(item: SubmissionForReview) -> Row:
    submission = item.submission
    status = submission.status
    file_state, file_tone = _file_state(submission)

    return Row(
        cells=(
            Cell(
                text=item.organization_name or "Deleted organization",
                href=_organization_url(submission.organization_id),
                muted=not item.organization_name,
            ),
            Cell(text=submission.agent.label),
            Cell(text=status.label, tone=STATUS_TONES[status]),
            Cell(text=_date(submission.submitted_at), muted=submission.submitted_at is None),
            Cell(text=file_state, tone=file_tone, muted=file_tone is None),
        )
    )


@console.register_tool
class AgentTranscriptsTool(ConsoleTool):
    key = QUEUE_TOOL_KEY
    title = "Agent transcripts"
    owner = GROWTH
    group = "Organizations"
    description = "Transcripts that organizations uploaded of their conversation with an AI agent, for review."

    def page(self, request: HttpRequest) -> Page:
        form = QueueFilterForm(request.GET if "status" in request.GET else None)
        status = _selected_status(form)

        requested_page = _page_number(request)
        submissions = api.list_submissions_for_review(
            status=status, limit=SUBMISSIONS_PER_PAGE, offset=(requested_page - 1) * SUBMISSIONS_PER_PAGE
        )
        num_pages = max(1, math.ceil(submissions.count / SUBMISSIONS_PER_PAGE))
        page_number = min(requested_page, num_pages)

        query = request.GET.copy()

        def page_url(number: int) -> str:
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        return Page(
            blocks=(
                Notice(
                    text=(
                        "Open an organization to download its transcript, then approve it, ask for changes or "
                        f"decline it. Each file is deleted {TRANSCRIPT_RETENTION_DAYS} days after upload."
                    )
                ),
                Filters(
                    form=form,
                    groups=(FieldGroup(title="Filter", field_names=("status",), inline=True),),
                    submit_label="Filter",
                    compact=True,
                ),
                Table(
                    columns=("Organization", "Agent", "Status", "Submitted", "File"),
                    rows=tuple(_queue_row(item) for item in submissions.results),
                    empty_text="No transcripts match.",
                ),
                *(
                    (
                        Paging(
                            number=page_number,
                            num_pages=num_pages,
                            summary=f"{submissions.count} transcripts",
                            previous_url=page_url(page_number - 1) if page_number > 1 else None,
                            next_url=page_url(page_number + 1) if page_number < num_pages else None,
                        ),
                    )
                    if submissions.count
                    else ()
                ),
            )
        )


class ApproveForm(forms.Form):
    merch_code = forms.CharField(
        required=False,
        max_length=MERCH_CODE_MAX_LENGTH,
        label="Merch code",
        help_text=(
            f"A ${MERCH_CODE_VALUE_USD} merch discount code from the pre-generated list. The customer gets it by email. "
            "Leave it empty to approve without a reward."
        ),
    )
    reason = forms.CharField(
        required=False,
        label=INTERNAL_NOTE_LABEL,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=INTERNAL_NOTE_HELP,
    )


class RequestChangesForm(forms.Form):
    review_message = forms.CharField(
        label=CUSTOMER_MESSAGE_LABEL,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "Emailed to the person who submitted the transcript, and shown on the transcript page in PostHog. "
            "Say what to change before they upload again."
        ),
    )
    reason = forms.CharField(
        required=False,
        label=INTERNAL_NOTE_LABEL,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=INTERNAL_NOTE_HELP,
    )


class DeclineForm(forms.Form):
    review_message = forms.CharField(
        label=CUSTOMER_MESSAGE_LABEL,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Emailed to the person who submitted the transcript, and shown on the transcript page in PostHog.",
    )
    # A decline cannot be undone, so the console needs a reason for its audit log. The reason is the internal note.
    reason = forms.CharField(
        label=INTERNAL_NOTE_LABEL,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=INTERNAL_NOTE_HELP,
    )


def _reviewer_id(request: HttpRequest) -> int:
    # The console runs behind admin_view, so the user is a signed-in staff member with a primary key.
    user_id = request.user.pk
    assert isinstance(user_id, int)
    return user_id


def _not_in_review(request: HttpRequest) -> HttpResponse:
    messages.error(request, NOT_IN_REVIEW_MESSAGE)
    return HttpResponse(status=409)


def download_transcript(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse:
    url = api.get_transcript_download_url(obj.pk)
    if url is None:
        messages.error(request, FILE_GONE_MESSAGE)
        return HttpResponse(status=410)

    return HttpResponseRedirect(url)


def open_in_viewer(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse:
    try:
        transcript = api.get_transcript_file(obj.pk)
    except TranscriptStorageUnavailable:
        messages.error(request, "Couldn't read the file from object storage. Try again.")
        return HttpResponse(status=502)
    if transcript is None:
        messages.error(request, FILE_GONE_MESSAGE)
        return HttpResponse(status=410)

    response = HttpResponse(transcript.content, content_type=transcript.content_type)
    response["Content-Disposition"] = f'attachment; filename="{transcript.filename}"'
    return response


def approve(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    merch_code = form.cleaned_data["merch_code"].strip()

    try:
        api.approve_submission(
            organization_id=obj.pk,
            reviewer_id=_reviewer_id(request),
            review_note=form.cleaned_data["reason"],
            merch_code=merch_code or None,
        )
    except DuplicateMerchCode:
        form.add_error("merch_code", "Another organization already has this code. Use the next code from the list.")
        return HttpResponse(status=409)
    except (InvalidSubmissionState, SubmissionNotFound):
        return _not_in_review(request)

    if merch_code:
        messages.success(request, f"Approved the transcript and emailed merch code {merch_code} to the submitter.")
    else:
        messages.success(request, "Approved the transcript without a merch code and emailed the submitter.")
    return None


def request_changes(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None

    try:
        api.request_changes(
            organization_id=obj.pk,
            reviewer_id=_reviewer_id(request),
            review_note=form.cleaned_data["reason"],
            review_message=form.cleaned_data["review_message"],
        )
    except (InvalidSubmissionState, SubmissionNotFound):
        return _not_in_review(request)

    messages.success(request, "Asked for changes and emailed your message to the submitter, who can upload again.")
    return None


def decline(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None

    try:
        api.decline_submission(
            organization_id=obj.pk,
            reviewer_id=_reviewer_id(request),
            review_note=form.cleaned_data["reason"],
            review_message=form.cleaned_data["review_message"],
        )
    except (InvalidSubmissionState, SubmissionNotFound):
        return _not_in_review(request)

    messages.success(request, "Declined the transcript and emailed your message to the submitter.")
    return None


def delete_file(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    try:
        api.delete_transcript_file(obj.pk)
    except SubmissionNotFound:
        messages.error(request, "This organization has no transcript.")
        return HttpResponse(status=404)
    except TranscriptStorageUnavailable:
        messages.error(request, "Couldn't delete the file from object storage, so nothing changed. Try again.")
        return HttpResponse(status=502)

    messages.success(request, "Deleted the transcript file.")
    return None


@console.register_panel
class AgentTranscriptPanel(Panel):
    record = "organization"
    key = PANEL_KEY
    title = "Agent transcript"
    owner = GROWTH
    operation_keys = frozenset(
        {
            DOWNLOAD_OPERATION,
            OPEN_IN_VIEWER_OPERATION,
            APPROVE_OPERATION,
            REQUEST_CHANGES_OPERATION,
            DECLINE_OPERATION,
            DELETE_FILE_OPERATION,
        }
    )

    def facts(self, obj: Model) -> list[Fact]:
        item = api.get_submission_for_review(obj.pk)
        if item is None:
            return [Fact(label="Transcript", value="Not submitted")]

        submission = item.submission
        facts = [
            Fact(label="Status", value=submission.status.label, tone=STATUS_TONES[submission.status]),
            Fact(label="Agent", value=submission.agent.label),
        ]

        if submission.submitted_at is not None:
            submitter = item.submitter
            facts.append(
                Fact(
                    label="Submitted",
                    value=f"{_submitter_text(submitter)} on {_date(submission.submitted_at)}",
                    href=reverse(RECORD_TYPES["user"].url_name, kwargs={"pk": submitter.user_id})
                    if submitter is not None
                    else None,
                )
            )
            size = f", {filesizeformat(submission.size_bytes)}" if submission.size_bytes is not None else ""
            facts.append(Fact(label="File", value=f"{submission.original_filename}{size}"))
            facts.append(Fact(label="Stored file", value=_stored_file_text(submission)))

        if submission.review_note:
            facts.append(Fact(label=INTERNAL_NOTE_LABEL, value=submission.review_note))
        if submission.review_message:
            facts.append(Fact(label=CUSTOMER_MESSAGE_LABEL, value=submission.review_message))
        if submission.merch_code:
            facts.append(Fact(label="Merch code", value=submission.merch_code, mono=True))

        return facts

    def operations(self, obj: Model) -> list[Operation]:
        submission = api.get_submission(obj.pk)
        if submission is None:
            return []

        operations: list[Operation] = []

        if submission.file_available:
            operations.append(
                Operation(
                    key=DOWNLOAD_OPERATION,
                    label="Download transcript",
                    handler=download_transcript,
                    description="Downloads the file through a link that works for one minute.",
                )
            )
            if settings.SITE_URL in HOGLOG_VIEWER_OPENERS:
                operations.append(
                    Operation(
                        key=OPEN_IN_VIEWER_OPERATION,
                        label="Open in Hoglog viewer",
                        handler=open_in_viewer,
                        description="Opens the transcript in Hoglog viewer in a new tab. The file goes from this page "
                        "to that tab and is not stored anywhere else.",
                        handoff=HOGLOG_VIEWER,
                    )
                )

        if submission.status == SubmissionStatus.SUBMITTED:
            operations.append(
                Operation(
                    key=APPROVE_OPERATION,
                    label="Approve transcript",
                    handler=approve,
                    form_class=ApproveForm,
                    description=(
                        "Accepts the transcript. The person who submitted it gets an email, with the merch code when "
                        "you add one."
                    ),
                )
            )
            operations.append(
                Operation(
                    key=REQUEST_CHANGES_OPERATION,
                    label="Ask for changes",
                    handler=request_changes,
                    form_class=RequestChangesForm,
                    description=(
                        "Sends the transcript back. The person who submitted it gets an email with your message, and "
                        "the organization can upload a new transcript."
                    ),
                )
            )
            operations.append(
                Operation(
                    key=DECLINE_OPERATION,
                    label="Decline transcript",
                    handler=decline,
                    danger=True,
                    form_class=DeclineForm,
                    description=(
                        "Declines the transcript for good. The person who submitted it gets an email with your "
                        "message, and the organization can't upload another transcript."
                    ),
                    undo_hint="This cannot be undone. The organization cannot submit another transcript.",
                )
            )

        if submission.file_available:
            operations.append(
                Operation(
                    key=DELETE_FILE_OPERATION,
                    label="Delete transcript file",
                    handler=delete_file,
                    danger=True,
                    form_class=ReasonForm,
                    description=(
                        f"Deletes the stored file now, instead of {TRANSCRIPT_RETENTION_DAYS} days after upload. The "
                        "submission and its review stay. The customer isn't told."
                    ),
                    undo_hint="This cannot be undone. Nobody can download or review the file afterwards.",
                )
            )

        return operations
