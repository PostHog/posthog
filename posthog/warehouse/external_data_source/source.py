import requests
from django.conf import settings
from posthog.models.utils import UUIDT
from pydantic import BaseModel, field_validator
from typing import Dict, Optional
import datetime as dt

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
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to create a source.")

    headers = {"accept": "application/json", "content-type": "application/json", "Authorization": f"Bearer {token}"}

    response = requests.post(AIRBYTE_SOURCE_URL, json=payload, headers=headers)
    response_payload = response.json()
    if not response.ok:
        raise ValueError(response_payload["message"])

    return ExternalDataSource(
        source_id=response_payload["sourceId"],
        name=response_payload["name"],
        source_type=response_payload["sourceType"],
        workspace_id=response_payload["workspaceId"],
    )


def delete_source(source_id):
    token = settings.AIRBYTE_API_KEY
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to delete a source.")
    headers = {"authorization": f"Bearer {token}"}

    response = requests.delete(AIRBYTE_SOURCE_URL + "/" + source_id, headers=headers)

    if not response.ok:
        raise ValueError(response.json()["message"])
