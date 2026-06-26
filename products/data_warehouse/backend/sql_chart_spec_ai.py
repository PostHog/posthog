"""AI generation of a quill `ChartSpec` mapping for SQL editor results.

The quill analogue of `sql_visualization_ai.py` (which generates Vega-Lite). The key difference:
quill charts are inert data, not an executable grammar, so there is no iframe sandbox downstream —
the frontend renders the spec directly. The model never sees full result data: it maps result
*columns* (which column is the x-axis, which become series, on which axis, in what format) and the
frontend fills in the real rows. That avoids hallucinated data and keeps the prompt small.
"""

from typing import Literal, Optional, TypedDict

import structlog
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from posthog.models.team import Team
from posthog.models.user import User

from ee.hogai.chat_agent.schema_generator.parsers import parse_pydantic_structured_output
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.helpers import dereference_schema

logger = structlog.get_logger(__name__)

ChartType = Literal["line", "bar", "combo", "timeSeriesLine", "timeSeriesBar", "pie", "metricCard"]
ValueFormat = Literal["numeric", "short", "percentage", "percentage_scaled", "currency", "duration", "duration_ms"]
AxisId = Literal["left", "right"]
SemanticType = Literal["temporal", "quantitative", "nominal", "ordinal"]


class ChartMappingAxis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: AxisId = Field(description="Which side this axis is on. Series target it via `axis`.")
    label: str | None = Field(default=None, description="Axis title.")
    format: ValueFormat | None = Field(default=None, description="Numeric format for ticks on this axis.")
    currency: str | None = Field(default=None, description="ISO currency code when format is 'currency'.")
    scale: Literal["linear", "log"] | None = Field(default=None)
    startAtZero: bool | None = Field(default=None, description="False floats the axis to the data range.")


class ChartMappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Layout
    stacked: bool | None = None
    grouped: bool | None = None
    percent: bool | None = None
    horizontal: bool | None = Field(default=None, description="Bar charts only: ranked horizontal layout.")
    donut: bool | None = Field(default=None, description="Pie charts only: standard donut (innerRadiusRatio 0.6).")
    innerRadiusRatio: float | None = Field(
        default=None,
        ge=0,
        le=0.95,
        description="Pie: inner radius fraction (0=pie, 0.4–0.7=donut, 0.85=thin ring). Overrides donut.",
    )

    # Legend
    showLegend: bool | None = None
    legendPosition: Literal["top", "bottom", "left", "right"] | None = Field(
        default=None, description="Where the legend sits. Default 'bottom'."
    )
    legendAlign: Literal["start", "center", "end"] | None = Field(
        default=None, description="Legend alignment along its axis. Default 'center'."
    )

    # Overlays
    showGrid: bool | None = None
    showAxisLines: bool | None = Field(default=None, description="Show L-shaped axis baselines without grid lines.")
    showCrosshair: bool | None = Field(default=None, description="Show a vertical crosshair following the cursor.")
    showValueLabels: bool | None = None

    # Axes
    hideXAxis: bool | None = None
    hideYAxis: bool | None = None

    # Tooltip
    tooltipShowTotal: bool | None = Field(default=None, description="Show a total row in the tooltip.")
    tooltipPlacement: Literal["follow-data", "top", "cursor"] | None = None

    # Bar-specific
    barFillStyle: Literal["flat", "gradient", "gloss"] | None = Field(default=None, description="Bar charts only.")
    divergingStack: bool | None = Field(default=None, description="Stacked bar: stack negatives below zero baseline.")
    roundStackEnds: bool | None = Field(default=None, description="Stacked bar: round outer ends as a pill.")

    # MetricCard-specific
    showChange: bool | None = Field(default=None, description="Metric card: show change/trend pill.")
    goodDirection: Literal["up", "down"] | None = Field(
        default=None, description="Metric card: which direction is good."
    )
    changeInline: bool | None = Field(default=None, description="Metric card: pill beside headline instead of header.")
    sparklineFill: bool | None = Field(default=None, description="Metric card: fill card height with sparkline.")
    subtitle: str | None = Field(default=None, description="Metric card: caption under the headline.")


class ChartMappingReferenceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | str = Field(description="Numeric value (horizontal line) or an x label (vertical marker).")
    orientation: Literal["horizontal", "vertical"] | None = None
    label: str | None = None
    variant: Literal["goal", "alert", "marker"] | None = None
    axis: AxisId | None = None


class ChartMappingSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(description="The result column name supplying this series' numeric values.")
    label: str | None = Field(default=None, description="Legend label. Defaults to the column name.")
    type: Literal["line", "bar", "area"] | None = Field(default=None, description="Combo charts only.")
    axis: AxisId | None = Field(default=None, description="Which axis to scale against. Defaults to 'left'.")


class ChartSpecMapping(BaseModel):
    """What the model emits: columns mapped to chart roles. The frontend turns this + the real rows
    into a renderable inline `ChartSpec`."""

    model_config = ConfigDict(extra="forbid")

    chartType: ChartType = Field(description="Chart family that best fits the columns.")
    title: str | None = Field(default=None, description="Short chart title.")
    narrative: str | None = Field(default=None, description="One plain sentence describing the takeaway.")
    xColumn: str = Field(description="Result column for the x-axis labels (or pie/metric category).")
    series: list[ChartMappingSeries] = Field(description="Result columns to plot as series (at least one).")
    axes: list[ChartMappingAxis] | None = Field(default=None, description="Axis defs; two for a dual-axis chart.")
    config: ChartMappingConfig | None = None
    referenceLines: list[ChartMappingReferenceLine] | None = None


class ChartSpecMappingOutput(BaseModel):
    mapping: ChartSpecMapping


class SQLChartColumn(TypedDict, total=False):
    name: str
    type: str | None
    semanticType: SemanticType
    sampleValues: list[object]


class SQLChartSpecPayload(TypedDict, total=False):
    query: str
    prompt: str
    columns: list[SQLChartColumn]
    sampleRows: list[dict[str, object]]
    rowCount: int


SYSTEM_PROMPT = """
You choose the best chart for a set of SQL query results and describe it as a `ChartSpecMapping`.
You do NOT receive or output the data — you only map result COLUMNS to chart roles. The frontend
fills in the real rows.

Guidelines:
- Pick `chartType` to fit the columns: a temporal column + numeric columns → `timeSeriesLine` for
  lines or `timeSeriesBar` for bars (both format dates correctly on the x-axis); a category column +
  a numeric column → `bar` (use `config.horizontal` for many categories ranked); part-of-whole → `pie`
  (`config.donut` for a donut); two numeric columns on different scales → `combo` with a dual axis;
  a single aggregate → `metricCard`. Never use `bar` when the x column contains ISO date strings —
  use `timeSeriesBar` instead.
- `xColumn` is the category/date column. `series` are the numeric columns to plot.
- Set value formatting per axis from the column's semanticType and name: money → `currency` (+ code),
  rates → `percentage`, durations → `duration`, large counts → `short`.
- For two series on different scales, give each `axis: 'left'`/`'right'` and define both in `axes`.
- Add a `referenceLines` goal line when the instruction mentions a target.
- Honor explicit layout requests: legend position/alignment → `config.legendPosition`/`config.legendAlign`; "hide axes" → `config.hideXAxis`/`config.hideYAxis`; "crosshair" → `config.showCrosshair`; "axis lines" → `config.showAxisLines`.
- Tooltip: "show total" → `config.tooltipShowTotal`; "pin tooltip" / "tooltip at top" → `config.tooltipPlacement: "top"`.
- Bar style: "gradient" / "gloss" → `config.barFillStyle`; negative data → `config.divergingStack`; "pill stack" → `config.roundStackEnds`.
- Pie: use `config.innerRadiusRatio` for precise ring width (e.g. 0.5 for standard, 0.8 for thin ring); `config.donut` is a shorthand for 0.6.
- Metric card: `config.showChange`, `config.goodDirection` ("lower is better" → "down"), `config.subtitle` for a caption, `config.sparklineFill` to fill the card height.
- Always set `narrative` to one plain sentence.

Reference only column names that appear in the provided columns. Return only the mapping.
""".strip()

USER_PROMPT = """
Instruction:
{{prompt}}

SQL query:
{{query}}

Result columns (name, type, semanticType, sample values):
{{columns}}

Row count: {{row_count}}
""".strip()


def _chart_mapping_schema() -> dict:
    return {
        "name": "output_chart_mapping",
        "description": "Maps SQL result columns to a quill chart.",
        "parameters": {
            "type": "object",
            "properties": {"mapping": dereference_schema(ChartSpecMapping.model_json_schema())},
            "additionalProperties": False,
            "required": ["mapping"],
        },
    }


CHART_MAPPING_SCHEMA = _chart_mapping_schema()


def infer_semantic_type(column_type: str | None) -> SemanticType:
    if not column_type:
        return "nominal"
    lowered = column_type.lower()
    if "date" in lowered or "time" in lowered:
        return "temporal"
    if any(token in lowered for token in ("int", "float", "decimal", "double", "numeric")):
        return "quantitative"
    return "nominal"


def _column_semantic_type(column: SQLChartColumn) -> SemanticType:
    return column.get("semanticType") or infer_semantic_type(column.get("type"))


def build_fallback_chart_mapping(payload: SQLChartSpecPayload) -> ChartSpecMapping:
    """Deterministic mapping from the result shape, used when AI generation fails."""
    columns = payload.get("columns", [])
    temporal = [c for c in columns if _column_semantic_type(c) == "temporal"]
    quantitative = [c for c in columns if _column_semantic_type(c) == "quantitative"]
    dimensions = [c for c in columns if _column_semantic_type(c) in ("nominal", "ordinal")]
    prompt = (payload.get("prompt") or "").lower()

    x_candidates = temporal or dimensions or columns
    x_column = x_candidates[0]["name"] if x_candidates else (columns[0]["name"] if columns else "x")
    value_columns = [c for c in quantitative if c["name"] != x_column] or [c for c in columns if c["name"] != x_column]
    series = [ChartMappingSeries(column=c["name"]) for c in value_columns[:5]] or [ChartMappingSeries(column=x_column)]

    if ("pie" in prompt or "donut" in prompt) and dimensions and quantitative:
        chart_type: ChartType = "pie"
        config = ChartMappingConfig(donut="donut" in prompt)
    elif temporal and quantitative:
        chart_type = "timeSeriesLine"
        config = ChartMappingConfig(showLegend=len(series) > 1)
    else:
        chart_type = "bar"
        config = ChartMappingConfig(horizontal=len(value_columns) <= 1, showLegend=len(series) > 1)

    return ChartSpecMapping(
        chartType=chart_type,
        narrative="Basic chart generated from the result shape.",
        xColumn=x_column,
        series=series,
        config=config,
    )


class SQLChartSpecGenerator:
    def __init__(self, team: Team, user: User) -> None:
        self._team = team
        self._user = user

    @property
    def _model(self) -> Runnable:
        return MaxChatAnthropic(
            model="claude-sonnet-4-6",
            temperature=0.3,
            streaming=False,
            user=self._user,
            team=self._team,
            max_tokens=4096,
            billable=True,
        ).with_structured_output(CHART_MAPPING_SCHEMA, include_raw=False)

    def _parse_output(self, output: dict) -> ChartSpecMapping:
        return parse_pydantic_structured_output(ChartSpecMappingOutput)(output).mapping

    async def agenerate(
        self, payload: SQLChartSpecPayload, config: Optional[RunnableConfig] = None
    ) -> ChartSpecMapping:
        prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", USER_PROMPT)],
            template_format="mustache",
        )
        chain = prompt | self._model | self._parse_output
        return await chain.ainvoke(
            {
                "prompt": payload.get("prompt") or "Visualize these results.",
                "query": payload.get("query") or "",
                "columns": _format_columns(payload.get("columns", [])),
                "row_count": payload.get("rowCount", 0),
            },
            config,
        )


def _format_columns(columns: list[SQLChartColumn]) -> str:
    lines = []
    for column in columns:
        samples = ", ".join(str(value) for value in (column.get("sampleValues") or [])[:5])
        lines.append(
            f"- {column.get('name')} ({column.get('type') or 'unknown'}, {_column_semantic_type(column)}): {samples}"
        )
    return "\n".join(lines)
