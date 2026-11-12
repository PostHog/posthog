from typing import cast

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.panels import Owner, ReasonForm
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Notice, Page, ToolOperation
from posthog.admin.console.usage_reports_tool import ReportDateForm
from posthog.models.user import User

from products.ai_observability.backend.facade.admin import (
    UsageReportRefused,
    dataset_retention_enabled,
    queue_usage_report,
    set_dataset_retention_enabled,
    usage_report_skips_existing_reports,
)

AI_OBSERVABILITY = Owner(name="AI observability", crest="ai-observability")

USAGE_REPORT_NOTICE = (
    "Usage report: the date is the day the report would have run, and the report covers the day before. "
    "If the dashboards are missing a day, send the report for the day after it. Sending a date again while its run "
    "is still going is refused. US and EU each report their own organizations, so backfill each region separately."
)
SKIPS_EXISTING_NOTICE = (
    "Organizations that already have a report for the period are skipped. This check cannot see a report sent in "
    "the last few minutes, so after a run finishes, wait for it to be ingested before you send the same date again."
)
CANNOT_SKIP_NOTICE = (
    "This region cannot check which organizations already have a report, because reports go to the US project. "
    "Sending a date that was already sent counts its usage twice, and the duplicates cannot be removed. Before you "
    "send, check the daily llm analytics usage event volume for that date in the internal usage-tracking project."
)
DATASET_CLEANUP_NOTICE = (
    "Cleanup permanently deletes unused active datasets after 90 days, and archived datasets and old revisions after "
    "30 days, with a 12-hour margin for recent use. Evaluation results and scores are kept. Pausing stops new expiry "
    "and deletion, including deletion in progress. A running sweep finishes its current dataset first. Expired "
    "datasets stay unavailable and deleted content is not restored. Resuming restarts the hourly schedule. Change "
    "this setting in each region separately."
)


def send_usage_report(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    report_date = form.cleaned_data["report_date"]
    try:
        queue_usage_report(report_date)
    except UsageReportRefused as refused:
        messages.error(request, refused.detail)
        return HttpResponse(status=400)
    messages.success(request, f"Queued the AI observability usage report for {report_date}.")
    return None


class DatasetCleanupHandler:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        set_dataset_retention_enabled(enabled=self.enabled, user_id=cast(User, request.user).pk)
        messages.success(request, f"Dataset cleanup is now {'on' if self.enabled else 'paused'} in this region.")
        return None


@console.register_tool
class AIObservabilityTool(ConsoleTool):
    key = "ai-observability"
    title = "AI observability"
    owner = AI_OBSERVABILITY
    group = "Data"
    description = "Sends a missing daily usage report, and pauses or resumes dataset cleanup in this region."

    def page(self, request: HttpRequest) -> Page:
        cleanup = "on" if dataset_retention_enabled() else "paused"
        return Page(
            blocks=(
                Notice(text=f"Dataset cleanup is {cleanup} in this region. {DATASET_CLEANUP_NOTICE}"),
                Notice(text=USAGE_REPORT_NOTICE),
                Notice(text=SKIPS_EXISTING_NOTICE if usage_report_skips_existing_reports() else CANNOT_SKIP_NOTICE),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        send = ToolOperation(
            key="send-usage-report",
            label="Send usage report",
            handler=send_usage_report,
            description="Queues the AI observability usage report of every organization in this region for one day.",
            form_class=ReportDateForm,
        )
        if dataset_retention_enabled():
            cleanup = ToolOperation(
                key="pause-dataset-cleanup",
                label="Pause dataset cleanup",
                handler=DatasetCleanupHandler(enabled=False),
                description="Stops expiring and deleting datasets in this region until cleanup is resumed.",
            )
        else:
            cleanup = ToolOperation(
                key="resume-dataset-cleanup",
                label="Resume dataset cleanup",
                handler=DatasetCleanupHandler(enabled=True),
                danger=True,
                description="Customers' unused and archived datasets in this region get deleted permanently again.",
                form_class=ReasonForm,
                undo_hint="To stop it, use Pause dataset cleanup. Datasets deleted in the meantime cannot be restored.",
            )
        return [send, cleanup]


console.register_moved_page(
    old_path="admin/posthog/organization/send-ai-observability-usage-report/",
    title="Sending AI observability usage reports",
    url="/admin/console/tools/ai-observability/",
)
console.register_moved_page(
    old_path="admin/posthog/organization/ai-observability-dataset-retention/",
    title="AI observability dataset retention",
    url="/admin/console/tools/ai-observability/",
)
