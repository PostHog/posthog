import datetime as dt
from typing import Dict, Optional

from pydantic import BaseModel, field_validator

from posthog.models.utils import UUIDT
from posthog.warehouse.external_data_source.client import send_request

AIRBYTE_SOURCE_URL = "https://api.airbyte.com/v1/sources"


class StripeSourcePayload(BaseModel):
    account_id: str
    client_secret: str
    start_date: Optional[dt.datetime] = None
    lookback_window_days: Optional[int] = None
    slice_range: Optional[int] = None

    @field_validator("account_id")
    @classmethod
    def account_id_is_valid_uuid(cls, v: str) -> str:
        try:
            UUIDT.is_valid_uuid(v)
        except ValueError:
            raise ValueError("account_id must be a valid UUID.")
        return v

    @field_validator("start_date")
    @classmethod
    def valid_iso_start_date(cls, v: Optional[str]) -> Optional[str]:
        from posthog.batch_exports.http import validate_date_input

        if not v:
            return v

        try:
            validate_date_input(v)
        except ValueError:
            raise ValueError("start_date must be a valid ISO date string.")
        return v


class ExternalDataSource(BaseModel):
    source_id: str
    name: str
    source_type: str
    workspace_id: str


def create_stripe_source(payload: StripeSourcePayload, workspace_id: str) -> ExternalDataSource:
    optional_config = {}
    if payload.start_date:
        optional_config["start_date"] = payload.start_date.isoformat()

    if payload.lookback_window_days:
        optional_config["lookback_window_days"] = payload.lookback_window_days

    if payload.slice_range:
        optional_config["slice_range"] = payload.slice_range

    payload = {
        "configuration": {
            "sourceType": "stripe",
            "account_id": payload.account_id,
            "client_secret": payload.client_secret,
            **optional_config,
        },
        "name": "stripe source",
        "workspaceId": workspace_id,
    }
    return _create_source(payload)


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
