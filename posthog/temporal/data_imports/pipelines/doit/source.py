import hashlib
from typing import Any
import pyarrow as pa
import requests
from dlt.common.normalizers.naming.snake_case import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_iterator
from posthog.temporal.data_imports.pipelines.source import config
from posthog.warehouse.types import IncrementalFieldType

DOIT_INCREMENTAL_FIELDS = [
    {
        "field": "timestamp",
        "field_type": IncrementalFieldType.Timestamp,
        "label": "timestamp",
        "type": IncrementalFieldType.Timestamp,
    }
]


@config.config
class DoItSourceConfig(config.Config):
    api_key: str


def build_pyarrow_schema(schema: dict[str, str]) -> pa.Schema:
    fields: list[pa.Field] = []
    for name, type in schema.items():
        arrow_type: pa.DataType

        match type:
            case "string":
                arrow_type = pa.string()
            case "float":
                arrow_type = pa.float64()
            case "timestamp":
                arrow_type = pa.timestamp("s")
            case "number":
                arrow_type = pa.int32()
            case "integer":
                arrow_type = pa.int32()
            case "boolean":
                arrow_type = pa.bool_()
            case _:
                arrow_type = pa.string()

        fields.append(pa.field(name, arrow_type, nullable=True))

    return pa.schema(fields)


def doit_list_reports(config: DoItSourceConfig) -> list[tuple[str, str]]:
    res = requests.get(
        "https://api.doit.com/analytics/v1/reports", headers={"Authorization": f"Bearer {config.api_key}"}
    )

    reports = res.json()["reports"]

    return [(NamingConvention().normalize_identifier(report["reportName"]), report["id"]) for report in reports]


def append_primary_key(row: dict[str, Any]) -> dict[str, Any]:
    columns_to_ignore = ["timestamp", "cost"]
    key = ""
    for name, value in row.items():
        if name not in columns_to_ignore:
            key = f"{key}-{value}"

    hash_key = hashlib.md5(key.encode()).hexdigest()

    return {**row, "id": hash_key}


def doit_source(
    config: DoItSourceConfig,
    report_name: str,
) -> SourceResponse:
    all_reports = doit_list_reports(config)
    selected_reports = [id for name, id in all_reports if name == report_name]
    if len(selected_reports) == 0:
        raise Exception("Report no longer exists")

    report_id = selected_reports[0]

    def get_rows(report_id: str):
        res = requests.get(
            f"https://api.doit.com/analytics/v1/reports/{report_id}",
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

        if res.status_code != 200:
            raise Exception(f"Request to get report failed with status: {res.status_code}. With body: {res.text}")

        result = res.json()

        schema: list[dict[str, str]] = result["result"]["schema"]
        column_names = [column["name"] for column in schema]
        column_types_dict = {column["name"]: column["type"] for column in schema}
        arrow_schema = build_pyarrow_schema(column_types_dict)

        rows: list[list[Any]] = result["result"]["rows"]

        yield table_from_iterator((append_primary_key(dict(zip(column_names, row))) for row in rows), arrow_schema)

    return SourceResponse(name=report_name, items=get_rows(report_id), primary_keys=["id"])
