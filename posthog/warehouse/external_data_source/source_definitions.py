from posthog.models.utils import UUIDT
from pydantic import BaseModel, field_validator
from typing import Optional
import datetime as dt


class SalesforceSourcePayload(BaseModel):
    client_id: str
    client_secret: str
    refresh_token: str
    sourceType: str = "salesforce"


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


SOURCE_TYPE_MAPPING = {
    "stripe": {
        "payload_type": StripeSourcePayload,
        "default_streams": ["customers"],
    },
    "salesforce": {
        "payload_type": SalesforceSourcePayload,
        "default_streams": ["accounts"],
    },
}
