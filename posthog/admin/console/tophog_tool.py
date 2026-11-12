import dataclasses
from datetime import UTC, datetime, timedelta
from itertools import groupby
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.text import Truncator

import structlog

from posthog.admin.console.panels import Owner, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, GroupRow, Live, Notice, Page, Row, Table, ToolOperation
from posthog.dataclasses import frozen
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig
from posthog.models.tophog.queries import TopHogFilterOptions, query_tophog_filter_options, query_tophog_metrics
from posthog.models.tophog.restrictions import (
    RESTRICTION_FILTER_FIELDS,
    extend_restriction,
    extendable_fields,
    find_restriction,
    key_token,
    map_pipelines,
    resolve_team_tokens,
    restriction_matches,
    restrictions_for_token,
    unmapped_pipelines,
)

logger = structlog.get_logger(__name__)

INGESTION = Owner(name="Ingestion", crest="ingestion")
TOOL_URL = "/admin/console/tools/tophog/"
REFRESH_SECONDS = 30
URL_TIME_FORMAT = "%Y-%m-%dT%H:%M"
DEFAULT_PRESET = "5m"
PRESET_MINUTES = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "3h": 180,
    "6h": 360,
    "12h": 720,
    "1d": 1440,
    "7d": 10080,
    "30d": 43200,
}
FILTER_FIELD_LABELS = {
    "distinct_ids": "distinct IDs",
    "session_ids": "session IDs",
    "event_names": "event names",
    "event_uuids": "event UUIDs",
}


@frozen
class TimeRange:
    date_from: datetime
    date_to: datetime
    # The preset the range ends now from, or None for a fixed range, which a link can pin.
    preset: str | None

    @staticmethod
    def last(preset: str) -> "TimeRange":
        now = datetime.now(UTC)
        return TimeRange(date_from=now - timedelta(minutes=PRESET_MINUTES[preset]), date_to=now, preset=preset)

    @staticmethod
    def from_request(request: HttpRequest) -> "TimeRange":
        raw_from = request.GET.get("date_from", "")
        raw_to = request.GET.get("date_to", "")
        if raw_from and raw_to:
            try:
                return TimeRange(
                    date_from=datetime.fromisoformat(raw_from).replace(tzinfo=UTC),
                    date_to=datetime.fromisoformat(raw_to).replace(tzinfo=UTC),
                    preset=None,
                )
            except ValueError:
                pass
        preset = request.GET.get("preset", DEFAULT_PRESET)
        return TimeRange.last(preset if preset in PRESET_MINUTES else DEFAULT_PRESET)

    def pinned(self) -> "TimeRange":
        return dataclasses.replace(self, preset=None)

    def query(self) -> dict[str, str]:
        if self.preset is not None:
            return {"preset": self.preset}
        return {
            "date_from": self.date_from.strftime(URL_TIME_FORMAT),
            "date_to": self.date_to.strftime(URL_TIME_FORMAT),
        }


@frozen
class DashboardFilters:
    time_range: TimeRange
    pipeline: str
    lane: str

    @staticmethod
    def from_request(request: HttpRequest) -> "DashboardFilters":
        return DashboardFilters(
            time_range=TimeRange.from_request(request),
            pipeline=request.GET.get("pipeline", ""),
            lane=request.GET.get("lane", ""),
        )

    def url(self) -> str:
        params = {**self.time_range.query(), "pipeline": self.pipeline, "lane": self.lane}
        return f"{TOOL_URL}?{urlencode({name: value for name, value in params.items() if value})}"


@frozen
class TopHogEntry:
    """One TopHog key, which the dashboard links to the restrictions of its token."""

    token: str
    key: dict[str, str]
    pipelines: list[str]

    @staticmethod
    def from_request(request: HttpRequest) -> "TopHogEntry":
        return TopHogEntry(
            token=request.GET.get("token", ""),
            key={
                name: request.GET.get(name, "")
                for name in request.GET
                if name not in ("token", "pipelines") and request.GET.get(name)
            },
            pipelines=[pipeline for pipeline in request.GET.get("pipelines", "").split(",") if pipeline],
        )

    def url(self) -> str:
        params = {"token": self.token, **{name: value for name, value in self.key.items() if name != "token"}}
        if self.pipelines:
            params["pipelines"] = ",".join(self.pipelines)
        return f"{TOOL_URL}?{urlencode(params)}"

    def create_restriction_url(self) -> str:
        """The Django admin add form of a restriction, filled in from this entry."""
        params = {"token": self.token}
        for key_field, config_field in RESTRICTION_FILTER_FIELDS.items():
            value = self.key.get(key_field)
            if value:
                params[config_field] = value
        restriction_pipelines = map_pipelines(self.pipelines)
        if restriction_pipelines:
            params["pipelines"] = ",".join(restriction_pipelines)
        return reverse("admin:posthog_eventingestionrestrictionconfig_add") + "?" + urlencode(params)


def _number(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _describe_key(key: dict[str, str]) -> str:
    return ", ".join(f"{name}: {value}" for name, value in key.items())


def _option(text: str, selected: bool, href: str) -> Cell:
    return Cell(text=text, tone=Tone.INFO) if selected else Cell(text=text, href=href)


def _filters_table(filters: DashboardFilters, options: TopHogFilterOptions) -> Table:
    columns = (
        [
            _option(
                preset,
                preset == filters.time_range.preset,
                dataclasses.replace(filters, time_range=TimeRange.last(preset)).url(),
            )
            for preset in PRESET_MINUTES
        ],
        [
            _option(
                pipeline or "All", pipeline == filters.pipeline, dataclasses.replace(filters, pipeline=pipeline).url()
            )
            for pipeline in ["", *options.pipelines]
        ],
        [
            _option(lane or "All", lane == filters.lane, dataclasses.replace(filters, lane=lane).url())
            for lane in ["", *options.lanes]
        ],
    )
    height = max(len(column) for column in columns)
    blank = Cell(text="")
    return Table(
        columns=("Time range", "Pipeline", "Lane"),
        rows=tuple(
            Row(cells=tuple(column[index] if index < len(column) else blank for column in columns))
            for index in range(height)
        ),
    )


def _range_notice(filters: DashboardFilters) -> Notice:
    time_range = filters.time_range
    text = (
        f"Top 10 keys of each metric from {time_range.date_from:%Y-%m-%d %H:%M} "
        f"to {time_range.date_to:%Y-%m-%d %H:%M} UTC."
    )
    if time_range.preset is None:
        latest = dataclasses.replace(filters, time_range=TimeRange.last(DEFAULT_PRESET))
        return Notice(text=text, link_text="Show the last 5 minutes", href=latest.url())
    pinned = dataclasses.replace(filters, time_range=time_range.pinned())
    return Notice(
        text=f"{text} The page refreshes every {REFRESH_SECONDS} seconds.",
        link_text="Pin this time range",
        href=pinned.url(),
    )


def _entries_table(rows: list[dict]) -> Table:
    tokens_by_team_id = resolve_team_tokens([row["key"] for row in rows])
    table_rows: list[Row | GroupRow] = []
    for (metric, metric_type), metric_rows in groupby(rows, key=lambda row: (row["metric"], row["type"])):
        table_rows.append(GroupRow(text=f"{metric} ({metric_type})"))
        for rank, row in enumerate(metric_rows, start=1):
            token = key_token(row["key"], tokens_by_team_id)
            entry = TopHogEntry(token=token, key=row["key"], pipelines=row["pipelines"])
            table_rows.append(
                Row(
                    cells=(
                        Cell(text=str(rank)),
                        Cell(text=_describe_key(row["key"]), mono=True),
                        Cell(text=token or "-", mono=bool(token), muted=not token),
                        Cell(text=_number(row["total"])),
                        Cell(text=_number(row["obs"])),
                        Cell(text=", ".join(row["pipelines"])),
                        Cell(text=", ".join(row["lanes"])),
                        Cell(text="Restrictions", href=entry.url()) if token else Cell(text="-", muted=True),
                    )
                )
            )
    return Table(
        columns=("Rank", "Key", "Token", "Value", "Count", "Pipeline", "Lane", "Restrictions"),
        rows=tuple(table_rows),
        empty_text="No TopHog data in this time range.",
    )


def _filter_values(values: list[str] | None) -> Cell:
    if not values:
        return Cell(text="All", muted=True)
    return Cell(text=Truncator(", ".join(values)).chars(80), mono=True)


def _restriction_row(restriction: EventIngestionRestrictionConfig, entry: TopHogEntry) -> Row:
    covers = restriction_matches(restriction, entry.key, entry.pipelines)
    return Row(
        cells=(
            Cell(text=restriction.get_restriction_type_display().capitalize()),
            Cell(text=", ".join(restriction.pipelines)),
            _filter_values(restriction.distinct_ids),
            _filter_values(restriction.session_ids),
            _filter_values(restriction.event_names),
            _filter_values(restriction.event_uuids),
            Cell(text=Truncator(restriction.note or "").chars(80)),
            Cell(text="Covers", tone=Tone.SUCCESS) if covers else Cell(text="Does not cover", tone=Tone.DEFAULT),
            Cell(
                text="Edit", href=reverse("admin:posthog_eventingestionrestrictionconfig_change", args=[restriction.pk])
            ),
        )
    )


def _pipelines_notice(entry: TopHogEntry) -> Notice:
    mapped = map_pipelines(entry.pipelines)
    unmapped = unmapped_pipelines(entry.pipelines)
    parts = []
    if mapped:
        parts.append(f"Restriction pipelines for this entry: {', '.join(mapped)}.")
    if unmapped:
        parts.append(f"No restriction pipeline matches {', '.join(unmapped)}, so no restriction can cover this entry.")
    return Notice(text=" ".join(parts))


class ExtendRestriction:
    def __init__(self, restriction_id: str, entry: TopHogEntry) -> None:
        self.restriction_id = restriction_id
        self.entry = entry

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        restriction = find_restriction(self.restriction_id, self.entry.token)
        if restriction is None:
            messages.error(request, "This restriction no longer exists. Go back to TopHog to see the current ones.")
            return HttpResponse(status=404)
        changed = extend_restriction(restriction, self.entry.key)
        if not changed:
            messages.info(request, "The restriction already covers this entry, so nothing changed.")
            return None
        labels = ", ".join(FILTER_FIELD_LABELS[field] for field in changed)
        messages.success(request, f"Added this entry to the {labels} of the restriction.")
        return None


@console.register_tool
class TopHogTool(ConsoleTool):
    key = "tophog"
    title = "TopHog"
    owner = INGESTION
    group = "Data"
    description = "The top keys of each ingestion metric, and the restrictions that cover them."

    def page(self, request: HttpRequest) -> Page:
        entry = TopHogEntry.from_request(request)
        if entry.token:
            return self._restrictions_page(entry)

        filters = DashboardFilters.from_request(request)
        try:
            options = query_tophog_filter_options(filters.time_range.date_from, filters.time_range.date_to)
        except Exception:
            logger.exception("admin_console_tophog_filter_options_failed")
            options = TopHogFilterOptions(pipelines=[], lanes=[])
        range_notice = self.live(request, "range")
        entries = self.live(request, "entries")
        assert range_notice is not None and entries is not None
        return Page(blocks=(range_notice, _filters_table(filters, options), entries))

    def live(self, request: HttpRequest, key: str) -> Live | None:
        if key not in ("range", "entries") or request.GET.get("token"):
            return None
        filters = DashboardFilters.from_request(request)
        time_range = filters.time_range
        refresh_seconds = REFRESH_SECONDS if time_range.preset is not None else None
        # The notice refreshes with the entries, so its times and pin link match the window on screen.
        if key == "range":
            return Live(key="range", block=_range_notice(filters), refresh_seconds=refresh_seconds)
        try:
            rows = query_tophog_metrics(
                time_range.date_from,
                time_range.date_to,
                pipeline=filters.pipeline or None,
                lane=filters.lane or None,
            )
        except Exception as error:
            logger.exception("admin_console_tophog_query_failed")
            return Live(
                key="entries",
                block=Notice(text=f"The TopHog query failed: {error}"),
                refresh_seconds=refresh_seconds,
            )
        return Live(key="entries", block=_entries_table(rows), refresh_seconds=refresh_seconds)

    def _restrictions_page(self, entry: TopHogEntry) -> Page:
        described_key = _describe_key(entry.key) or "no key fields"
        return Page(
            blocks=(
                Notice(
                    text=f"Restrictions on token {entry.token}, for the entry {described_key}.",
                    link_text="Back to TopHog",
                    href=TOOL_URL,
                ),
                *((_pipelines_notice(entry),) if entry.pipelines else ()),
                Table(
                    columns=(
                        "Type",
                        "Pipelines",
                        "Distinct IDs",
                        "Session IDs",
                        "Event names",
                        "Event UUIDs",
                        "Note",
                        "This entry",
                        "Django admin",
                    ),
                    rows=tuple(
                        _restriction_row(restriction, entry) for restriction in restrictions_for_token(entry.token)
                    ),
                    empty_text="This token has no restrictions.",
                ),
                Notice(
                    text="To restrict this entry in a new way, add a restriction filled in from it.",
                    link_text="Create a restriction",
                    href=entry.create_restriction_url(),
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        entry = TopHogEntry.from_request(request)
        if not entry.token:
            return []
        operations = []
        for restriction in restrictions_for_token(entry.token):
            fields = extendable_fields(restriction, entry.key)
            if not fields:
                continue
            labels = ", ".join(FILTER_FIELD_LABELS[field] for field in fields)
            operations.append(
                ToolOperation(
                    key=f"extend-{restriction.pk}",
                    label=f"Extend the {restriction.get_restriction_type_display().lower()} restriction",
                    handler=ExtendRestriction(str(restriction.pk), entry),
                    danger=True,
                    form_class=ReasonForm,
                    description=(
                        f"Adds this entry to the {labels} of the restriction, "
                        "so ingestion applies it to these events too."
                    ),
                    undo_hint="Edit the restriction in Django admin and remove the added values.",
                )
            )
        return operations


console.register_moved_page(old_path="admin/tophog/", title="TopHog", url=TOOL_URL)
console.register_moved_page(old_path="admin/tophog/restrictions/", title="TopHog restrictions", url=TOOL_URL)
