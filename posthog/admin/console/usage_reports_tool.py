from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from posthog.admin.console.organization_panels import BILLING
from posthog.admin.console.panels import Gate
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Notice, Page, ToolOperation


class ReportDateForm(forms.Form):
    report_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="The day the report would have run, which reports usage of the day before.",
    )

    def clean_report_date(self):
        report_date = self.cleaned_data["report_date"]
        if report_date > (timezone.now().date() + timedelta(days=1)):
            raise forms.ValidationError("The date cannot be more than one day in the future.")
        return report_date


def send_usage_report(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    report_date = form.cleaned_data["report_date"]
    call_command("send_usage_report", f"--date={report_date.strftime('%Y-%m-%d')}", "--async=1")
    messages.success(request, f"Queued the usage reports for {report_date}.")
    return None


@console.register_tool
class UsageReportsTool(ConsoleTool):
    key = "usage-reports"
    title = "Usage reports"
    owner = BILLING
    group = "Billing"
    description = "Sends the daily usage reports again for a day they are missing."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "A report reports usage of the day before its date. If reports are missing for May 11, "
                        "send them for May 12. Read more at posthog.com/docs/advanced/usage-reports."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="send",
                label="Send usage report",
                handler=send_usage_report,
                description="Queues the usage reports of every organization for one day.",
                form_class=ReportDateForm,
                # Usage reports go to the billing service and customers get invoiced on them, so only billing
                # staff send one.
                gate=Gate.owner(),
            )
        ]


console.register_moved_page(
    old_path="admin/posthog/organization/send-usage-report/",
    title="Sending usage reports",
    url="/admin/console/tools/usage-reports/",
)
