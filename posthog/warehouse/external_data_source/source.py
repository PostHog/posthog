from pydantic import BaseModel
from typing import Dict
from posthog.warehouse.external_data_source.client import send_request
from posthog.warehouse.external_data_source.source_definitions import SOURCE_TYPE_MAPPING

AIRBYTE_SOURCE_URL = "https://api.airbyte.com/v1/sources"


class ExternalDataSource(BaseModel):
    source_id: str
    name: str
    source_type: str
    workspace_id: str


def create_source(source_type: str, payload: Dict, workspace_id: str) -> ExternalDataSource:
    try:
        source_payload = SOURCE_TYPE_MAPPING[source_type]["payload_type"](**payload)
    except Exception as e:
        raise ValueError(f"Invalid payload for source type {source_type}: {e}")

    request_payload = {
        "configuration": {
            "sourceType": source_type,
            **source_payload.dict(),
        },
        "name": f"{source_type} source",
        "workspaceId": workspace_id,
    }

    return _create_source(request_payload)


def _create_source(payload: Dict) -> ExternalDataSource:
    response = send_request(AIRBYTE_SOURCE_URL, method="POST", payload=payload)
    return ExternalDataSource(
        source_id=response["sourceId"],
        name=response["name"],
        source_type=response["sourceType"],
        workspace_id=response["workspaceId"],
    )


def delete_source(source_id):
    send_request(AIRBYTE_SOURCE_URL + "/" + source_id, method="DELETE")
