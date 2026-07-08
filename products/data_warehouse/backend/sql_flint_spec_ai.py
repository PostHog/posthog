"""AI generation of a Flint chart spec for SQL editor results.

The Flint analogue of the earlier quill `ChartSpec` mapping experiment. The model emits only a
compact, inert Flint spec — chart type, channel encodings, and per-column semantic types — and the
flint-chart compiler derives everything else (scales, sort order, zero baselines, formatting,
layout) deterministically on the client. The model never sees full result data: it maps result
columns to channels and the frontend fills in the real rows.
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

# The chart types the quill Flint backend implements (frontend/src/lib/charts/flint/templates)
FlintChartType = Literal[
    "Line Chart",
    "Area Chart",
    "Bar Chart",
    "Grouped Bar Chart",
    "Stacked Bar Chart",
    "Pie Chart",
    "Doughnut Chart",
]


class FlintEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str | None = Field(default=None, description="Result column name bound to this channel.")
    aggregate: Literal["count", "sum", "average"] | None = Field(
        default=None, description="Aggregate rows onto this channel instead of (or as well as) a column."
    )


class FlintEncodings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: FlintEncoding | None = Field(default=None, description="X axis (category or date column).")
    y: list[FlintEncoding] | None = Field(
        default=None, description="Measures to plot. Multiple entries become one series each."
    )
    color: FlintEncoding | None = Field(
        default=None, description="Series split (cartesian charts) or slice category (pie charts)."
    )
    size: FlintEncoding | None = Field(default=None, description="Slice value column (pie charts only).")


class FlintChartProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stackMode: Literal["normalize"] | None = Field(
        default=None,
        description="'normalize' stacks to 100% (share of total). Stacked Bar and Area charts only.",
    )


class FlintChartSpec(BaseModel):
    """What the model emits: a Flint chart spec. The flint-chart compiler derives axes, scales,
    sort order, zero baselines, formatting, and layout from this plus the real rows."""

    model_config = ConfigDict(extra="forbid")

    chartType: FlintChartType = Field(description="Flint chart template that best fits the columns.")
    encodings: FlintEncodings = Field(description="Column-to-channel bindings.")
    chartProperties: FlintChartProperties | None = Field(
        default=None, description="Template-specific display properties."
    )
    semantic_types: dict[str, str] = Field(
        description=(
            "Per-column Flint semantic type, e.g. Date, Quantity, Price, Percentage, Duration, "
            "Category, Country, Rank. Drives formatting, zero baselines, and sort order."
        )
    )
    narrative: str | None = Field(default=None, description="One plain sentence describing the takeaway.")


class FlintSpecOutput(BaseModel):
    spec: FlintChartSpec


class SQLFlintColumn(TypedDict, total=False):
    name: str
    type: str | None
    sampleValues: list[object]


class SQLFlintSpecPayload(TypedDict, total=False):
    query: str
    prompt: str
    columns: list[SQLFlintColumn]
    rowCount: int


SYSTEM_PROMPT = """
You choose the best chart for a set of SQL query results and describe it as a compact Flint chart
spec. You do NOT receive or output the data — you map result COLUMNS to encoding channels, and a
deterministic compiler derives scales, axes, sort order, number/date formatting, and layout.

Guidelines:
- Cartesian charts bind `x` (the category or date column) and `y` (one entry per measure column).
  Bind `color` to a categorical column to split one measure into series — never bind `color` and
  multiple `y` entries at once.
- Pie/Doughnut charts bind `color` (slice category) and `size` (slice value) instead of x/y.
- A date column on x with measures → "Line Chart" (or "Area Chart"/"Stacked Bar Chart" for
  composition over time). A category column on x → "Bar Chart" ("Grouped"/"Stacked" with a color
  split). Part-of-whole → "Pie Chart" or "Doughnut Chart".
- When rows are not pre-aggregated, set `aggregate` on y ("count" needs no field).
- "Share of total" / "as a percentage" / "100% stacked" → a "Stacked Bar Chart" or "Area Chart"
  with `chartProperties.stackMode` = "normalize".
- `semantic_types` must cover every referenced column with its meaning, not its storage type:
  money → Price, ratios/rates → Percentage, timestamps/dates → Date, counts/amounts → Quantity,
  time spans → Duration, names/labels → Category, rankings → Rank, geography → Country.
- Set `narrative` to one plain sentence.

Reference only column names that appear in the provided columns. Return only the spec.
""".strip()

USER_PROMPT = """
Instruction:
{{prompt}}

SQL query:
{{query}}

Result columns (name, type, sample values):
{{columns}}

Row count: {{row_count}}
""".strip()


def _flint_spec_schema() -> dict:
    return {
        "name": "output_flint_spec",
        "description": "Maps SQL result columns to a Flint chart spec.",
        "parameters": {
            "type": "object",
            "properties": {"spec": dereference_schema(FlintChartSpec.model_json_schema())},
            "additionalProperties": False,
            "required": ["spec"],
        },
    }


FLINT_SPEC_SCHEMA = _flint_spec_schema()


def validate_spec_columns(spec: FlintChartSpec, columns: list[SQLFlintColumn]) -> None:
    """Reject specs that reference columns not present in the results."""
    known = {column.get("name") for column in columns}
    referenced: list[str] = []
    for encoding in [spec.encodings.x, spec.encodings.color, spec.encodings.size, *(spec.encodings.y or [])]:
        if encoding and encoding.field:
            referenced.append(encoding.field)
    unknown = [field for field in referenced if field not in known]
    if unknown:
        raise ValueError(f"Spec references unknown columns: {', '.join(unknown)}")


class SQLFlintSpecGenerator:
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
            max_tokens=2048,
            billable=True,
        ).with_structured_output(FLINT_SPEC_SCHEMA, include_raw=False)

    def _parse_output(self, output: dict) -> FlintChartSpec:
        return parse_pydantic_structured_output(FlintSpecOutput)(output).spec

    async def agenerate(self, payload: SQLFlintSpecPayload, config: Optional[RunnableConfig] = None) -> FlintChartSpec:
        prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", USER_PROMPT)],
            template_format="mustache",
        )
        chain = prompt | self._model | self._parse_output
        spec = await chain.ainvoke(
            {
                "prompt": payload.get("prompt") or "Visualize these results.",
                "query": payload.get("query") or "",
                "columns": _format_columns(payload.get("columns", [])),
                "row_count": payload.get("rowCount", 0),
            },
            config,
        )
        validate_spec_columns(spec, payload.get("columns", []))
        return spec


def _format_columns(columns: list[SQLFlintColumn]) -> str:
    lines = []
    for column in columns:
        samples = ", ".join(str(value) for value in (column.get("sampleValues") or [])[:5])
        lines.append(f"- {column.get('name')} ({column.get('type') or 'unknown'}): {samples}")
    return "\n".join(lines)
