from datetime import UTC, datetime, timedelta
from typing import Any

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.http import urlencode

from posthog.admin.console.panels import Owner, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.models.distinct_id_usage.report import (
    DistinctIdUsage,
    RestrictionRefused,
    TokenRestriction,
    UsageThresholds,
)
from posthog.models.event_ingestion_restriction_config import RestrictionType
from posthog.models.team.team import Team

INGESTION = Owner(name="Ingestion", crest="ingestion")
TOOL_URL = "/admin/console/tools/distinct-id-usage/"
RESTRICT_URL = f"{TOOL_URL}restrict/"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
DEFAULT_HOURS = 6
# The table keeps 7 days of data, so a longer range reads nothing more.
MAX_RANGE_DAYS = 7
RESTRICTION_CHOICES = [
    (RestrictionType.SKIP_PERSON_PROCESSING, "Skip person processing"),
    (RestrictionType.DROP_EVENT_FROM_INGESTION, "Drop events"),
    (RestrictionType.FORCE_OVERFLOW_FROM_INGESTION, "Force overflow"),
]


def _datetime_field(label: str) -> forms.DateTimeField:
    return forms.DateTimeField(
        label=label,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_FORMAT),
        input_formats=[DATETIME_FORMAT],
    )


class DistinctIdUsageForm(forms.Form):
    datetime_from = _datetime_field("From (UTC)")
    datetime_to = _datetime_field("To (UTC)")
    high_usage_percentage_threshold = forms.IntegerField(
        initial=30,
        min_value=1,
        max_value=100,
        label="High usage share (%)",
        help_text="Share of a team's events that come from one distinct ID.",
    )
    high_usage_min_events_threshold = forms.IntegerField(
        initial=10_000,
        min_value=1,
        label="Minimum team events",
        help_text="Teams with fewer events in the range are left out of high usage.",
    )
    high_usage_distinct_id_min_events = forms.IntegerField(
        initial=100_000,
        min_value=1,
        label="Minimum distinct ID events",
        help_text="Distinct IDs with fewer events in the range are left out of high usage.",
    )
    high_cardinality_threshold = forms.IntegerField(
        initial=1_000_000,
        min_value=1,
        label="High cardinality",
        help_text="Unique distinct IDs per team.",
    )
    burst_distinct_id_threshold = forms.IntegerField(
        initial=100_000,
        min_value=1,
        label="Burst by distinct ID",
        help_text="Events per minute from one distinct ID of a team.",
    )
    burst_team_threshold = forms.IntegerField(
        initial=500_000,
        min_value=1,
        label="Burst by team",
        help_text="Events per minute from one team.",
    )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        dt_from = cleaned.get("datetime_from")
        dt_to = cleaned.get("datetime_to")
        if dt_from and dt_to:
            if dt_from >= dt_to:
                raise forms.ValidationError("From must be before To.")
            if (dt_to - dt_from).days > MAX_RANGE_DAYS:
                raise forms.ValidationError(f"Pick a range of {MAX_RANGE_DAYS} days or less. Older data is deleted.")
        return cleaned

    def thresholds(self) -> UsageThresholds:
        return UsageThresholds(
            high_usage_percentage=self.cleaned_data["high_usage_percentage_threshold"],
            high_usage_min_team_events=self.cleaned_data["high_usage_min_events_threshold"],
            high_usage_min_distinct_id_events=self.cleaned_data["high_usage_distinct_id_min_events"],
            high_cardinality=self.cleaned_data["high_cardinality_threshold"],
            distinct_id_burst=self.cleaned_data["burst_distinct_id_threshold"],
            team_burst=self.cleaned_data["burst_team_threshold"],
        )


REPORT_FIELDS = tuple(DistinctIdUsageForm.base_fields)


class RestrictDistinctIdForm(forms.Form):
    token = forms.CharField(label="Project token", max_length=100)
    # Capture keeps surrounding spaces and restrictions match exactly, so the ID is saved as typed.
    distinct_id = forms.CharField(label="Distinct ID", max_length=450, strip=False)
    restriction_type = forms.ChoiceField(
        label="Restriction", choices=RESTRICTION_CHOICES, initial=RestrictionType.SKIP_PERSON_PROCESSING
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def clean_token(self) -> str:
        token = self.cleaned_data["token"].strip()
        if not Team.objects.filter(api_token=token).exists():
            raise forms.ValidationError("No project has this token.")
        return token


def run_report(request: HttpRequest, form: forms.Form | None) -> HttpResponse:
    assert form is not None
    # The report shows on the tool page, so its URL can be bookmarked and shared like the old page's.
    query = urlencode({name: form.data[name] for name in REPORT_FIELDS})
    return HttpResponseRedirect(f"{TOOL_URL}?{query}")


def restrict_distinct_id(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    token = form.cleaned_data["token"]
    try:
        change = DistinctIdUsage.restrict(
            token, form.cleaned_data["restriction_type"], form.cleaned_data["distinct_id"]
        )
    except RestrictionRefused as refused:
        messages.error(request, str(refused))
        return HttpResponse(status=400)
    short_token = f"{token[:16]}…"
    if change.created:
        messages.success(request, f"Created a {change.label} restriction for {short_token} with this distinct ID.")
    elif change.added:
        messages.success(request, f"Added the distinct ID to the {change.label} restriction for {short_token}.")
    else:
        messages.info(request, f"The distinct ID is already in the {change.label} restriction for {short_token}.")
    return None


def _restrict_url(request: HttpRequest, token: str, distinct_id: str, restriction_type: str | None = None) -> str:
    # The report parameters stay in the link, so staff land back on the same report after the restriction.
    query = request.GET.copy()
    query["token"] = token
    query["distinct_id"] = distinct_id
    query.pop("restriction_type", None)
    if restriction_type is not None:
        query["restriction_type"] = restriction_type
    return f"{RESTRICT_URL}?{query.urlencode()}"


def _change_url(restriction: TokenRestriction) -> str:
    return reverse("admin:posthog_eventingestionrestrictionconfig_change", args=[restriction.id])


def _team_cell(team_id: int) -> Cell:
    return Cell(text=str(team_id), href=reverse("admin_console_team", kwargs={"pk": team_id}))


def _count(value: int) -> Cell:
    return Cell(text=f"{value:,}")


def _distinct_id_restriction_cell(
    request: HttpRequest, token: str, distinct_id: str, restrictions: tuple[TokenRestriction, ...]
) -> Cell:
    if not restrictions:
        return Cell(text="-", muted=True)
    for restriction in restrictions:
        if not restriction.distinct_ids:
            return Cell(text=f"Applied to all: {restriction.label}", href=_change_url(restriction), tone=Tone.SUCCESS)
        if distinct_id in restriction.distinct_ids:
            return Cell(text=f"Applied: {restriction.label}", href=_change_url(restriction), tone=Tone.SUCCESS)
    # These cells carry no tone, because the table renders a toned cell as a badge without its link.
    restrictable_types = {choice for choice, _label in RESTRICTION_CHOICES}
    for restriction in restrictions:
        if restriction.restriction_type in restrictable_types:
            return Cell(
                text=f"Not in list: {restriction.label}",
                href=_restrict_url(request, token, distinct_id, restriction.restriction_type),
            )
    # The restrict form offers no redirect types, so the link leaves the type to staff.
    return Cell(text=f"Not in list: {restrictions[0].label}", href=_restrict_url(request, token, distinct_id))


def _team_restriction_cell(restrictions: tuple[TokenRestriction, ...]) -> Cell:
    if not restrictions:
        return Cell(text="-", muted=True)
    first = restrictions[0]
    more = len(restrictions) - 1
    return Cell(text=first.label + (f" and {more} more" if more else ""), href=_change_url(first))


def _action_cell(request: HttpRequest, token: str, distinct_id: str) -> Cell:
    if not token:
        return Cell(text="No token", muted=True)
    return Cell(text="Restrict", href=_restrict_url(request, token, distinct_id))


def _report_initial(request: HttpRequest) -> dict[str, object]:
    now = datetime.now(tz=UTC)
    initial: dict[str, object] = {
        "datetime_from": (now - timedelta(hours=DEFAULT_HOURS)).strftime(DATETIME_FORMAT),
        "datetime_to": now.strftime(DATETIME_FORMAT),
    }
    initial.update({name: request.GET[name] for name in REPORT_FIELDS if name in request.GET})
    return initial


@console.register_tool
class DistinctIdUsageTool(ConsoleTool):
    key = "distinct-id-usage"
    title = "Distinct ID usage"
    owner = INGESTION
    group = "Data"
    description = "Finds distinct IDs and teams that send unusually many events, and restricts their ingestion."

    def page(self, request: HttpRequest) -> Page:
        if "datetime_from" not in request.GET:
            return Page(
                blocks=(
                    Notice(
                        text=(
                            "Run the report to find distinct IDs and teams that send unusually many events. "
                            f"The data covers the last {MAX_RANGE_DAYS} days."
                        )
                    ),
                )
            )
        form = DistinctIdUsageForm(request.GET)
        if not form.is_valid():
            problems = " ".join(str(error) for errors in form.errors.values() for error in errors)
            return Page(blocks=(Notice(text=f"The report did not run. {problems} Run the report again."),))

        thresholds = form.thresholds()
        report = DistinctIdUsage.report(
            form.cleaned_data["datetime_from"], form.cleaned_data["datetime_to"], thresholds
        )
        return Page(
            blocks=(
                *(Notice(text=error) for error in report.errors),
                Notice(
                    text=(
                        f"High usage distinct IDs: {len(report.high_usage)}. One distinct ID sends at least "
                        f"{thresholds.high_usage_percentage}% of its team's events."
                    )
                ),
                Table(
                    columns=("Team", "Distinct ID", "Restriction", "Events", "Team events", "Share", "Action"),
                    rows=tuple(
                        Row(
                            cells=(
                                _team_cell(row.team_id),
                                Cell(text=row.distinct_id, mono=True),
                                _distinct_id_restriction_cell(request, row.token, row.distinct_id, row.restrictions),
                                _count(row.event_count),
                                _count(row.team_event_count),
                                Cell(text=f"{row.percentage}%"),
                                _action_cell(request, row.token, row.distinct_id),
                            )
                        )
                        for row in report.high_usage
                    ),
                    empty_text="No distinct ID passes these thresholds.",
                ),
                Notice(
                    text=(
                        f"High cardinality teams: {len(report.high_cardinality)}. A team has at least "
                        f"{thresholds.high_cardinality:,} unique distinct IDs."
                    )
                ),
                Table(
                    columns=("Team", "Restriction", "Unique distinct IDs"),
                    rows=tuple(
                        Row(
                            cells=(
                                _team_cell(row.team_id),
                                _team_restriction_cell(row.restrictions),
                                _count(row.distinct_id_count),
                            )
                        )
                        for row in report.high_cardinality
                    ),
                    empty_text="No team passes this threshold.",
                ),
                Notice(
                    text=(
                        f"Bursts by distinct ID: {len(report.distinct_id_bursts)}. One distinct ID sends at least "
                        f"{thresholds.distinct_id_burst:,} events in a minute."
                    )
                ),
                Table(
                    columns=("Team", "Distinct ID", "Restriction", "Minute", "Events per minute", "Action"),
                    rows=tuple(
                        Row(
                            cells=(
                                _team_cell(row.team_id),
                                Cell(text=row.distinct_id, mono=True),
                                _distinct_id_restriction_cell(request, row.token, row.distinct_id, row.restrictions),
                                Cell(text=row.minute.strftime("%Y-%m-%d %H:%M")),
                                _count(row.event_count),
                                _action_cell(request, row.token, row.distinct_id),
                            )
                        )
                        for row in report.distinct_id_bursts
                    ),
                    empty_text="No distinct ID passes this threshold.",
                ),
                Notice(
                    text=(
                        f"Bursts by team: {len(report.team_bursts)}. One team sends at least "
                        f"{thresholds.team_burst:,} events in a minute."
                    )
                ),
                Table(
                    columns=("Team", "Restriction", "Minute", "Events per minute"),
                    rows=tuple(
                        Row(
                            cells=(
                                _team_cell(row.team_id),
                                _team_restriction_cell(row.restrictions),
                                Cell(text=row.minute.strftime("%Y-%m-%d %H:%M")),
                                _count(row.event_count),
                            )
                        )
                        for row in report.team_bursts
                    ),
                    empty_text="No team passes this threshold.",
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="run",
                label="Run report",
                handler=run_report,
                description="Reads the event counts of the time range, and lists what passes the thresholds.",
                form_class=DistinctIdUsageForm,
                form_initial=_report_initial(request),
            ),
            ToolOperation(
                key="restrict",
                label="Restrict a distinct ID",
                handler=restrict_distinct_id,
                danger=True,
                description=(
                    "Adds the distinct ID to the project's ingestion restriction of this type. Creates the "
                    "restriction when the project has none."
                ),
                form_class=RestrictDistinctIdForm,
                form_initial={
                    name: request.GET[name]
                    for name in ("token", "distinct_id", "restriction_type")
                    if name in request.GET
                },
                undo_hint=(
                    "To undo, remove the distinct ID from the restriction in Django admin, under Event ingestion "
                    "restriction configs."
                ),
            ),
        ]


console.register_moved_page(old_path="admin/distinct-id-usage/", title="Distinct ID usage", url=TOOL_URL)
