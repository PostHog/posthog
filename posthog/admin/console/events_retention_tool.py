from datetime import UTC, datetime
from itertools import groupby

from django.core.paginator import Paginator
from django.http import HttpRequest
from django.urls import reverse

from posthog.admin.console.panels import Owner
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, GroupRow, Notice, Page, Paging, Row, Table
from posthog.models.events_retention_config import (
    ConfiguredEventsRetention,
    configured_events_retention,
    count_configured_events_retention,
    describe_months_range,
    whole_month_cutoff,
)

TEAMS_PER_PAGE = 100
CLICKHOUSE = Owner(name="ClickHouse", crest="clickhouse")


def _months(value: int | None) -> Cell:
    return Cell(text=f"{value} months") if value is not None else Cell(text="-", muted=True)


def _source(retention: ConfiguredEventsRetention) -> str:
    if retention.team_months is not None:
        return "Team setting"
    if retention.organization_default_months is not None:
        return "Organization default"
    return "Not set, events are kept"


def _organization_row(retention: ConfiguredEventsRetention) -> GroupRow:
    low, high = retention.organization_min_months, retention.organization_max_months
    allowed = describe_months_range(low, high) if low is not None or high is not None else "any number of months"
    default = (
        f"{retention.organization_default_months} months"
        if retention.organization_default_months is not None
        else "not set"
    )
    return GroupRow(
        text=retention.organization_name,
        detail=f"Default: {default} · Allowed: {allowed}",
        href=reverse("admin:posthog_organization_change", args=[retention.organization_id]),
    )


def _team_row(retention: ConfiguredEventsRetention, now: datetime) -> Row:
    deletes_before = whole_month_cutoff(now, retention.months) if retention.months is not None else None
    cells = (
        Cell(
            text=f"{retention.team_name} ({retention.team_id})",
            href=reverse("admin_console_team", kwargs={"team_id": retention.team_id}),
        ),
        Cell(text=f"{retention.billing_months} months"),
        _months(retention.team_months),
        _months(retention.months),
        Cell(text=_source(retention)),
        Cell(text=deletes_before.strftime("%B %Y")) if deletes_before else Cell(text="-", muted=True),
    )
    return Row(cells=cells)


@console.register_tool
class EventsRetentionTool(ConsoleTool):
    key = "events-retention"
    title = "Events retention"
    owner = CLICKHOUSE
    group = "Data"
    description = "Deletion retention per team, and the month the monthly cleanup deletes up to."

    def page(self, request: HttpRequest) -> Page:
        # The paginator only works out the page bounds, so the query reads the rows of one page.
        page = Paginator(range(count_configured_events_retention()), TEAMS_PER_PAGE).get_page(request.GET.get("page"))
        retention = configured_events_retention(offset=max(page.start_index() - 1, 0), limit=len(page.object_list))
        now = datetime.now(UTC)

        rows: list[Row | GroupRow] = []
        for _organization_id, teams in groupby(retention, key=lambda item: item.organization_id):
            team_list = list(teams)
            rows.append(_organization_row(team_list[0]))
            rows.extend(_team_row(item, now) for item in team_list)

        return Page(
            blocks=(
                Notice(
                    text=(
                        "Billing months is Team.event_retention_months, which the billing plan sets. It only hides "
                        "older events in queries. Deletion retention is the staff setting that the monthly cleanup "
                        "enforces. The cleanup deletes one calendar month at a time, and only when every event in "
                        "that month is older than the retention."
                    )
                ),
                Table(
                    columns=("Team", "Billing months", "Team setting", "Retention", "Source", "Deletes months before"),
                    rows=tuple(rows),
                    empty_text="No team has a deletion retention yet. Set one on the organization or team page.",
                ),
                Paging(
                    number=page.number,
                    num_pages=page.paginator.num_pages,
                    summary=f"{page.paginator.count} teams",
                    previous_url=f"?page={page.previous_page_number()}" if page.has_previous() else None,
                    next_url=f"?page={page.next_page_number()}" if page.has_next() else None,
                ),
            )
        )
