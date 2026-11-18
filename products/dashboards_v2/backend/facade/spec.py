"""The dashboard document: the JSON stored in `DashboardV2.spec`, its versions and its drafts.

These models are the single definition of the document. The API declares them in its OpenAPI schema, so the
generated frontend types and MCP tool schemas follow from them.

Keys are camelCase in JSON (`refId`, `fieldConfig`) so documents stay compatible with Dash and with Grafana's
naming. Python attributes are snake_case.

Validation has two levels. A draft is any object with a `uid`, so an edit that breaks a panel is still saved and
the panel shows an error. Publishing parses the full schema and checks references between its parts.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, ValidationError
from pydantic.alias_generators import to_camel

TITLE_MAX = 300
DESCRIPTION_MAX = 10_000
FOLDER_MAX = 500
TAG_MAX = 100
TAGS_MAX = 100
GRID_COLUMNS = 24

UID_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,62}$"
VARIABLE_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
REQUIREMENT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"

VIZ_TYPES = (
    "timeseries",
    "bar",
    "pie",
    "stat",
    "gauge",
    "table",
    "text",
    "heatmap",
    "retention",
    "boxplot",
    "sankey",
    "flamegraph",
    "logs",
    "traces",
    "dashlist",
    "geomap",
)
VIZ_TYPES_WITHOUT_QUERIES = frozenset({"text", "dashlist"})

QueryLanguage = Literal["promql", "hogql", "sql", "logql", "insight"]
Display = Literal["spacious", "dense"]


class _SpecModel(BaseModel):
    # Unknown keys are dropped on publish, the same as Dash's zod schema, so a typo cannot persist unnoticed.
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="ignore",
    )


class TimeRange(_SpecModel):
    from_: str = Field(alias="from")
    to: str


class _VariableBase(_SpecModel):
    name: str = Field(pattern=VARIABLE_NAME_PATTERN)
    label: str | None = None
    hidden: bool | None = None
    multi: bool | None = None
    include_all: bool | None = None
    all_value: str | None = None
    current: str | list[str] | None = None


class CustomVariable(_VariableBase):
    type: Literal["custom"]
    options: list[str]


class QueryVariable(_VariableBase):
    type: Literal["query"]
    language: QueryLanguage
    query: str
    regex: str | None = None


class TextboxVariable(_VariableBase):
    type: Literal["textbox"]
    default: str | None = None


class IntervalVariable(_VariableBase):
    type: Literal["interval"]
    options: list[str]


class ConstantVariable(_VariableBase):
    type: Literal["constant"]
    value: str


class AdhocVariable(_VariableBase):
    type: Literal["adhoc"]


Variable = Annotated[
    CustomVariable | QueryVariable | TextboxVariable | IntervalVariable | ConstantVariable | AdhocVariable,
    Field(discriminator="type"),
]


class BuilderState(_SpecModel):
    model_config = ConfigDict(extra="allow")

    source: Literal["metrics", "logs", "events", "traces"]


class Target(_SpecModel):
    ref_id: str
    language: QueryLanguage
    query: str
    legend: str | None = None
    bucketed: bool | None = None
    instant: bool | None = None
    format: Literal["time_series", "table"] | None = None
    hide: bool | None = None
    builder: BuilderState | None = None
    built_by: str | None = None


class Threshold(_SpecModel):
    value: float
    color: str
    label: str | None = None


class Mapping(_SpecModel):
    value: str | None = None
    from_: float | None = Field(default=None, alias="from")
    to: float | None = None
    null: bool | None = None
    text: str | None = None
    color: str | None = None


class ColorScheme(_SpecModel):
    mode: str
    fixed_color: str | None = None
    series_by: Literal["last", "mean", "max", "min"] | None = None


class FieldOverride(_SpecModel):
    unit: str | None = None
    decimals: int | None = Field(default=None, ge=0, le=10)
    color: str | None = None
    display_name: str | None = None
    hidden: bool | None = None
    style: Literal["line", "bars", "points"] | None = None
    stack: bool | None = None
    fill: float | None = Field(default=None, ge=0, le=1)
    dash: list[Annotated[float, Field(ge=0)]] | None = None
    width: float | None = Field(default=None, ge=0, le=10)
    axis: Literal["left", "right"] | None = None
    negate: bool | None = None
    cell: Literal["bar", "color-background", "color-text"] | None = None
    link: str | None = None
    wrap: bool | None = None
    mappings: list[Mapping] | None = None


class FieldConfig(_SpecModel):
    unit: str | None = None
    decimals: int | None = Field(default=None, ge=0, le=10)
    min: float | None = None
    max: float | None = None
    soft_min: float | None = None
    soft_max: float | None = None
    thresholds: list[Threshold] | None = None
    color: ColorScheme | None = None
    # Keyed by an exact field or series name, a `/regex/flags`, or `#<position>`.
    overrides: dict[str, FieldOverride] | None = None
    mappings: list[Mapping] | None = None


class Viz(_SpecModel):
    # Any string is stored so that a draft with an unknown type still saves. Publishing checks it against VIZ_TYPES.
    type: str
    options: dict[str, Any] | None = None


class PartitionTransform(_SpecModel):
    type: Literal["partition"]
    by: str


class OrganizeTransform(_SpecModel):
    type: Literal["organize"]
    fields: list[str] = Field(min_length=1)


class MergeTransform(_SpecModel):
    type: Literal["merge"]
    on: str


class LimitTransform(_SpecModel):
    type: Literal["limit"]
    n: int = Field(gt=0)


class SortTransform(_SpecModel):
    type: Literal["sort"]
    field: str
    desc: bool | None = None


class RenameTransform(_SpecModel):
    type: Literal["rename"]
    from_: str = Field(alias="from")
    to: str


class MathTransform(_SpecModel):
    type: Literal["math"]
    as_: str = Field(alias="as")
    expression: str
    mode: Literal["value", "series"] | None = None


Transform = Annotated[
    PartitionTransform
    | OrganizeTransform
    | MergeTransform
    | LimitTransform
    | SortTransform
    | RenameTransform
    | MathTransform,
    Field(discriminator="type"),
]


class UrlAction(_SpecModel):
    type: Literal["url"]
    url: str
    new_tab: bool | None = None


class DashboardAction(_SpecModel):
    type: Literal["dashboard"]
    uid: str
    vars: dict[str, str] | None = None
    time: Literal["keep", "clicked"] | None = None


class VariableAction(_SpecModel):
    type: Literal["variable"]
    name: str
    value: str


class PanelAction(_SpecModel):
    type: Literal["panel"]
    # A whole panel, templated with the click. It is not validated here because its strings hold placeholders.
    panel: dict[str, Any]
    time: Literal["clicked", "dashboard"] | None = None


class PeopleAction(_SpecModel):
    type: Literal["people"]


class EventsAction(_SpecModel):
    type: Literal["events"]


class ZoomAction(_SpecModel):
    type: Literal["zoom"]


class ExploreAction(_SpecModel):
    type: Literal["explore"]


DrilldownAction = Annotated[
    UrlAction
    | DashboardAction
    | VariableAction
    | PanelAction
    | PeopleAction
    | EventsAction
    | ZoomAction
    | ExploreAction,
    Field(discriminator="type"),
]


class Drilldown(_SpecModel):
    title: str
    action: DrilldownAction


class DashboardLink(_SpecModel):
    title: str
    type: Literal["link", "dashboards"] | None = None
    url: str | None = None
    tags: list[str] | None = None
    as_dropdown: bool | None = None
    icon: Literal["external", "dashboard", "doc", "info", "bell", "grafana", "github"] | None = None
    tooltip: str | None = None
    new_tab: bool | None = None
    keep_time: bool | None = None
    include_vars: bool | None = None


class PanelCache(_SpecModel):
    ttl: str | None = None


class Panel(_SpecModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    description_mode: Literal["info", "below", "hidden"] | None = None
    hide_when_empty: bool | None = None
    viz: Viz
    targets: list[Target] | None = None
    transforms: list[Transform] | None = None
    field_config: FieldConfig | None = None
    cache: PanelCache | None = None
    precompute: bool | None = None
    interval: str | None = None
    time_from: str | None = None
    time_shift: str | None = None
    compare: str | None = None
    incomplete: Literal["solid", "dashed", "estimate", "hidden"] | None = None
    drilldowns: list[Drilldown] | None = None
    links: list[DashboardLink] | None = None
    max_data_points: int | None = Field(default=None, gt=0)
    builder: BuilderState | None = None
    requires: list[str] | None = None


class PanelItem(_SpecModel):
    panel: str
    x: int = Field(ge=0, le=GRID_COLUMNS - 1)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1)


class RowItem(_SpecModel):
    row: str
    y: int = Field(ge=0)
    collapsed: bool | None = None
    repeat: str | None = None
    items: list[PanelItem]


class Tab(_SpecModel):
    title: str
    items: list[PanelItem]


class TabsItem(_SpecModel):
    tabs: str
    y: int = Field(ge=0)
    items: list[Tab]


def _layout_item_kind(value: Any) -> str | None:
    # The kinds share no `type` key: each is told apart by the key that names it.
    keys = value.keys() if isinstance(value, dict) else vars(value)
    for kind in ("panel", "row", "tabs"):
        if kind in keys:
            return kind
    return None


LayoutItem = Annotated[
    Annotated[PanelItem, Tag("panel")] | Annotated[RowItem, Tag("row")] | Annotated[TabsItem, Tag("tabs")],
    Discriminator(_layout_item_kind),
]


class Layout(_SpecModel):
    type: Literal["grid"]
    columns: Literal[24] = 24
    items: list[LayoutItem]


class Requirement(_SpecModel):
    id: str = Field(pattern=REQUIREMENT_ID_PATTERN)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    kind: Literal["event", "sdk", "warehouse", "metric", "query"]
    why: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    optional: bool | None = None
    event: str | None = None
    bind: str | None = None
    property: str | None = None
    table: str | None = None
    metric: str | None = None
    language: QueryLanguage | None = None
    query: str | None = None
    setup: str | None = Field(default=None, max_length=DESCRIPTION_MAX)


class Dashboard(_SpecModel):
    uid: str = Field(pattern=UID_PATTERN)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    folder: str | None = Field(default=None, max_length=FOLDER_MAX)
    tags: list[Annotated[str, Field(max_length=TAG_MAX)]] | None = Field(default=None, max_length=TAGS_MAX)
    links: list[DashboardLink] | None = None
    link_style: Literal["buttons", "tabs"] | None = None
    # How the dashboard draws. Unset means dense, so documents from before this field look as they did.
    display: Display | None = None
    time: TimeRange = Field(default_factory=lambda: TimeRange.model_validate({"from": "now-6h", "to": "now"}))
    refresh: str | None = None
    timezone: str | None = None
    variables: list[Variable] = Field(default_factory=list)
    layout: Layout
    panels: dict[str, Panel]
    requires: list[Requirement] | None = None


class DashboardDraft(BaseModel):
    """A draft document: any object with a `uid`. All other keys are kept as they are."""

    model_config = ConfigDict(extra="allow")

    uid: str


class ValidationIssue(BaseModel):
    path: str
    message: str


class SpecValidationError(Exception):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        super().__init__("; ".join(f"{i.path}: {i.message}" for i in issues))
        self.issues = issues


def display_of(spec: dict[str, Any] | None) -> Display:
    # A draft can hold any value, so anything other than "spacious" draws dense.
    return "spacious" if spec is not None and spec.get("display") == "spacious" else "dense"


def to_document(dashboard: Dashboard) -> dict[str, Any]:
    """The JSON to store, with defaults filled in and unset optional keys left out."""
    return dashboard.model_dump(mode="json", exclude_none=True)


def parse_draft(document: object) -> DashboardDraft:
    try:
        return DashboardDraft.model_validate(document)
    except ValidationError as e:
        raise SpecValidationError(_issues_from(e)) from e


def parse_publish(document: object) -> Dashboard:
    try:
        dashboard = Dashboard.model_validate(document)
    except ValidationError as e:
        raise SpecValidationError(_issues_from(e)) from e
    issues = (
        _reference_issues(dashboard) + _variable_issues(dashboard) + _panel_issues(dashboard) + _grid_issues(dashboard)
    )
    if issues:
        raise SpecValidationError(issues)
    return dashboard


def layout_panel_ids(layout: Layout) -> list[str]:
    ids: list[str] = []
    for item in layout.items:
        if isinstance(item, PanelItem):
            ids.append(item.panel)
        elif isinstance(item, RowItem):
            ids.extend(p.panel for p in item.items)
        else:
            ids.extend(p.panel for tab in item.items for p in tab.items)
    return ids


def _issues_from(error: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(path=".".join(str(part) for part in e["loc"]) or "(root)", message=e["msg"])
        for e in error.errors()
    ]


def _reference_issues(dashboard: Dashboard) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    placed = layout_panel_ids(dashboard.layout)
    seen: set[str] = set()
    for panel_id in placed:
        if panel_id not in dashboard.panels:
            issues.append(ValidationIssue(path="layout", message=f'layout references unknown panel "{panel_id}"'))
        if panel_id in seen:
            issues.append(ValidationIssue(path="layout", message=f'panel "{panel_id}" is placed twice'))
        seen.add(panel_id)
    for panel_id in dashboard.panels:
        if panel_id not in seen:
            issues.append(
                ValidationIssue(path=f"panels.{panel_id}", message=f'panel "{panel_id}" is not placed in the layout')
            )
    return issues


def _variable_issues(dashboard: Dashboard) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    names: set[str] = set()
    for variable in dashboard.variables:
        if variable.name in names:
            issues.append(ValidationIssue(path="variables", message=f'duplicate variable "{variable.name}"'))
        names.add(variable.name)
    return issues


def _panel_issues(dashboard: Dashboard) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for panel_id, panel in dashboard.panels.items():
        if panel.viz.type not in VIZ_TYPES:
            issues.append(
                ValidationIssue(
                    path=f"panels.{panel_id}.viz.type",
                    message=f'unknown viz type "{panel.viz.type}" (known: {", ".join(VIZ_TYPES)})',
                )
            )
        elif (
            panel.viz.type not in VIZ_TYPES_WITHOUT_QUERIES
            and not any(not t.hide for t in panel.targets or [])
            # A math transform runs the hidden queries it reads, so the panel still has data.
            and not any(isinstance(t, MathTransform) for t in panel.transforms or [])
        ):
            issues.append(
                ValidationIssue(path=f"panels.{panel_id}.targets", message=f'panel "{panel_id}" has no queries')
            )
    return issues


def _grid_issues(dashboard: Dashboard) -> list[ValidationIssue]:
    # Each container (the top level, each row, each tab) is its own 24-column grid. Overlaps are allowed because
    # the grid packs items upward when it draws them.
    issues: list[ValidationIssue] = []

    def check(where: str, items: list[PanelItem]) -> None:
        for item in items:
            if item.x + item.w > GRID_COLUMNS:
                issues.append(
                    ValidationIssue(
                        path=where,
                        message=f'panel "{item.panel}" spills past column {GRID_COLUMNS} (x {item.x} + w {item.w})',
                    )
                )

    check("layout", [i for i in dashboard.layout.items if isinstance(i, PanelItem)])
    for item in dashboard.layout.items:
        if isinstance(item, RowItem):
            check(f'layout.row "{item.row}"', item.items)
        elif isinstance(item, TabsItem):
            for tab in item.items:
                check(f'layout.tabs "{item.tabs}" / "{tab.title}"', tab.items)
    return issues
