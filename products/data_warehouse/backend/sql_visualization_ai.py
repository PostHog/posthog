import json
from typing import Literal, TypedDict

import structlog
import posthoganalytics
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel, ConfigDict, Field

from posthog.models.team import Team
from posthog.models.user import User

from ee.hogai.llm import MaxChatOpenAI

SemanticType = Literal["temporal", "quantitative", "nominal", "ordinal"]
VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"
POSTHOG_RESULTS_DATASET = "posthog_results"
SQL_VISUALIZATION_AI_TIMEOUT_SECONDS = 15

logger = structlog.get_logger(__name__)


class SQLVisualizationColumn(TypedDict, total=False):
    name: str
    type: str | None
    semanticType: SemanticType
    sampleValues: list[object]
    nullCount: int
    distinctSampleCount: int


class SQLVisualizationField(TypedDict, total=False):
    field: str
    sourceColumn: str
    label: str
    type: str | None
    semanticType: SemanticType


class SQLVisualizationView(TypedDict):
    width: int
    height: int


class SQLVisualizationGenerationPayload(TypedDict, total=False):
    query: str
    prompt: str
    columns: list[SQLVisualizationColumn]
    fields: list[SQLVisualizationField]
    sampleRows: list[dict[str, object]]
    rowCount: int
    view: SQLVisualizationView


class SQLVisualizationGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, object] = Field(description="A Vega-Lite JSON specification object.")
    explanation: str | None = Field(default=None, description="Short explanation of the chosen chart.")
    warnings: list[str] = Field(default_factory=list, description="Warnings about limitations in the generated chart.")


SYSTEM_PROMPT = """
You generate safe Vega-Lite visualizations for PostHog SQL query results.

Return a Vega-Lite spec that uses the named data source `posthog_results`.
Use only the provided fields. If field aliases are present, use the alias in the `field` property and use labels in titles.

Allowed top-level keys include unit and composition Vega-Lite specs such as mark, encoding, layer, concat, facet, config, width, and height.
Required data block: {"name": "posthog_results"}.
Allowed marks include bar, line, area, point, circle, rect, arc, tick, rule, text, trail, boxplot, errorbar, and errorband.
Use the provided view width and height to choose a readable layout. Prefer width "container" and a numeric height that fits the view.

Do not include external data, URLs, inline data.values, datasets, transforms, params, selections, JavaScript, HTML, hrefs, image marks, geoshapes, projections, event streams, or expression strings.
Prefer simple readable charts when appropriate, but richer Vega-Lite marks are fine when they make the result clearer.
""".strip()

USER_PROMPT = """
Visualization prompt:
{{prompt}}

SQL query:
{{query}}

Compact result shape:
{{result_shape}}
""".strip()


def _infer_semantic_type(column_type: str | None) -> SemanticType:
    if not column_type:
        return "nominal"

    lowered_type = column_type.lower()
    if "date" in lowered_type or "time" in lowered_type:
        return "temporal"
    if any(token in lowered_type for token in ("int", "float", "decimal", "double", "numeric")):
        return "quantitative"
    return "nominal"


def _payload_fields(payload: SQLVisualizationGenerationPayload) -> list[SQLVisualizationField]:
    fields = payload.get("fields") or []
    if fields:
        return fields

    generated_fields: list[SQLVisualizationField] = []
    for index, column in enumerate(payload.get("columns", [])):
        source_column = column.get("name", f"field_{index}")
        column_type = column.get("type")
        generated_fields.append(
            {
                "field": f"field_{index}",
                "sourceColumn": source_column,
                "label": source_column,
                "type": column_type,
                "semanticType": column.get("semanticType") or _infer_semantic_type(column_type),
            }
        )
    return generated_fields


def _field_semantic_type(field: SQLVisualizationField) -> SemanticType:
    return field.get("semanticType") or _infer_semantic_type(field.get("type"))


def _encoding_field(field: SQLVisualizationField) -> dict[str, object]:
    field_name = field["field"]
    return {
        "field": field_name,
        "type": _field_semantic_type(field),
        "title": field.get("label") or field.get("sourceColumn") or field_name,
    }


def build_fallback_sql_visualization(
    payload: SQLVisualizationGenerationPayload,
) -> SQLVisualizationGenerationOutput:
    fields = [field for field in _payload_fields(payload) if field.get("field")]
    quantitative_fields = [field for field in fields if _field_semantic_type(field) == "quantitative"]
    temporal_fields = [field for field in fields if _field_semantic_type(field) == "temporal"]
    dimension_fields = [field for field in fields if _field_semantic_type(field) in ("nominal", "ordinal")]

    mark: str | dict[str, object] = "bar"
    encoding: dict[str, object] = {}
    warnings: list[str] = ["AI generation failed, so a basic chart was generated from the result shape."]
    prompt = payload.get("prompt", "").lower()
    wants_arc_chart = "pie" in prompt or "donut" in prompt

    if wants_arc_chart and dimension_fields and quantitative_fields:
        mark = "arc"
        encoding = {
            "theta": _encoding_field(quantitative_fields[0]),
            "color": _encoding_field(dimension_fields[0]),
        }
        if "donut" in prompt:
            mark = {"type": "arc", "innerRadius": 60}
        if payload.get("rowCount", 0) > 25:
            warnings.append("Pie charts can be hard to read with many categories.")
    elif temporal_fields and quantitative_fields:
        mark = "line"
        encoding = {
            "x": _encoding_field(temporal_fields[0]),
            "y": _encoding_field(quantitative_fields[0]),
        }
    elif dimension_fields and quantitative_fields:
        mark = "bar"
        encoding = {
            "x": {**_encoding_field(dimension_fields[0]), "sort": "-y"},
            "y": _encoding_field(quantitative_fields[0]),
        }
    elif len(quantitative_fields) >= 2:
        mark = "point"
        encoding = {
            "x": _encoding_field(quantitative_fields[0]),
            "y": _encoding_field(quantitative_fields[1]),
        }
    elif fields:
        mark = "bar"
        encoding = {
            "x": _encoding_field(fields[0]),
        }

    if fields:
        encoding["tooltip"] = [_encoding_field(field) for field in fields[:8]]

    return SQLVisualizationGenerationOutput(
        spec={
            "$schema": VEGA_LITE_SCHEMA,
            "title": "Generated SQL visualization",
            "data": {"name": POSTHOG_RESULTS_DATASET},
            "width": "container",
            "height": 320,
            "mark": mark,
            "encoding": encoding,
            "config": {"view": {"stroke": None}},
        },
        explanation="Generated a basic chart from the SQL result shape.",
        warnings=warnings,
    )


def generate_sql_visualization(
    *,
    payload: SQLVisualizationGenerationPayload,
    team: Team,
    user: User,
    trace_id: str,
) -> SQLVisualizationGenerationOutput:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT),
        ],
        template_format="mustache",
    )
    result_shape = {
        "columns": payload.get("columns", []),
        "fields": payload.get("fields", []),
        "sampleRows": payload.get("sampleRows", []),
        "rowCount": payload.get("rowCount", 0),
        "view": payload.get("view", {}),
    }
    messages = prompt.format_messages(
        prompt=payload.get("prompt", ""),
        query=payload.get("query", ""),
        result_shape=json.dumps(result_shape, default=str, ensure_ascii=False),
    )

    config: RunnableConfig = {
        "configurable": {
            "team": team,
            "user": user,
            "trace_id": trace_id,
            "distinct_id": user.distinct_id,
        },
        "callbacks": (
            [CallbackHandler(posthoganalytics.default_client, distinct_id=user.distinct_id, trace_id=trace_id)]
            if posthoganalytics.default_client
            else None
        ),
    }

    model = MaxChatOpenAI(
        model="gpt-4.1",
        temperature=0,
        disable_streaming=True,
        timeout=SQL_VISUALIZATION_AI_TIMEOUT_SECONDS,
        max_retries=0,
        user=user,
        team=team,
        billable=True,
        inject_context=False,
    ).with_structured_output(SQLVisualizationGenerationOutput, method="function_calling", include_raw=False)

    try:
        result = model.invoke(messages, config=config)
        if isinstance(result, SQLVisualizationGenerationOutput):
            return result
        return SQLVisualizationGenerationOutput.model_validate(result)
    except Exception:
        logger.warning(
            "sql_visualization.ai_generation_failed",
            team_id=team.id,
            trace_id=trace_id,
            exc_info=True,
        )
        return build_fallback_sql_visualization(payload)
