from typing import Optional

from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
    PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING,
    PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING,
)


class SourceHandler:
    """Base class for source handlers."""

    def __init__(self, request_data: dict, team_id: Optional[int] = None):
        self.request_data = request_data
        self.team_id = team_id

    def validate_credentials(self) -> tuple[bool, str | None]:
        """Validate source credentials. Returns (is_valid, error_message)"""
        return True, None

    def get_schema_options(self) -> list[dict]:
        """Get schema options for the source. Returns list of table options"""
        raise NotImplementedError

    def _get_explicit_schema_options(self, source_type: str) -> list[dict]:
        schemas = PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING.get(source_type, None)
        incremental_schemas = PIPELINE_TYPE_INCREMENTAL_ENDPOINTS_MAPPING.get(source_type, ())
        incremental_fields = PIPELINE_TYPE_INCREMENTAL_FIELDS_MAPPING.get(source_type, {})

        if schemas is None:
            return []

        return [
            {
                "table": row,
                "should_sync": False,
                "incremental_fields": [
                    {
                        "label": field["label"],
                        "type": field["type"],
                        "field": field["field"],
                        "field_type": field["field_type"],
                    }
                    for field in incremental_fields.get(row, [])
                ],
                "incremental_available": row in incremental_schemas,
                "incremental_field": (
                    incremental_fields.get(row, [])[0]["field"]
                    if row in incremental_schemas and incremental_fields.get(row, [])
                    else None
                ),
                "sync_type": None,
            }
            for row in schemas
        ]
