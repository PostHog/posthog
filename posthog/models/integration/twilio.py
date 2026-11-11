"""Twilio integration."""

from typing import TYPE_CHECKING

from rest_framework.exceptions import ValidationError

from posthog.integrations.contracts import IntegrationRecord

from . import model

NOT_AN_ACCOUNT_SID_MESSAGE = (
    "This is not an account SID. Account SIDs start with AC and are 34 characters long. "
    "Copy yours from the Twilio Console."
)
CREDENTIALS_REJECTED_MESSAGE = "Twilio rejected these credentials. Check your account SID and auth token."
BLANK_AUTH_TOKEN_MESSAGE = "Enter your auth token. Copy it from the Twilio Console."
SAVED_CREDENTIALS_REJECTED_MESSAGE = (
    "Twilio rejected the saved credentials. "
    "In Channels, add Twilio again with the same account SID and your current auth token."
)

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.workflows.backend.facade.contracts import TwilioPhoneNumber


class TwilioIntegration:
    integration: model.Integration

    def __init__(self, integration: IntegrationRecord) -> None:
        if integration.kind != "twilio":
            raise Exception("TwilioIntegration init called with Integration with wrong 'kind'")
        self.integration = model.integration_model(integration)
        self._account_sid = self.integration.config["account_sid"]
        self._auth_token = self.integration.sensitive_config["auth_token"]

    @classmethod
    def integration_from_credentials(
        cls, *, account_sid: str, auth_token: str, team_id: int, created_by: "User | None"
    ) -> model.Integration:
        """Check the typed-in credentials with Twilio, then create or update the team's row for the account."""
        account_sid = account_sid.strip() if isinstance(account_sid, str) else ""
        auth_token = auth_token.strip() if isinstance(auth_token, str) else ""
        if not (account_sid.startswith("AC") and len(account_sid) == 34):
            raise ValidationError({"account_sid": NOT_AN_ACCOUNT_SID_MESSAGE})
        if not auth_token:
            raise ValidationError({"auth_token": BLANK_AUTH_TOKEN_MESSAGE})
        unsaved = model.Integration(
            team_id=team_id,
            created_by=created_by,
            kind="twilio",
            config={"account_sid": account_sid},
            sensitive_config={"auth_token": auth_token},
        )
        return cls(unsaved).integration_from_keys()

    def list_twilio_phone_numbers(self) -> list["TwilioPhoneNumber"]:
        from products.workflows.backend.facade.api import (
            get_twilio_phone_numbers,  # noqa: PLC0415 — keeps the workflows facade off the model import path
        )
        from products.workflows.backend.facade.contracts import TwilioCredentialsRejected  # noqa: PLC0415

        try:
            return get_twilio_phone_numbers(account_sid=self._account_sid, auth_token=self._auth_token)
        except TwilioCredentialsRejected:
            raise ValidationError(SAVED_CREDENTIALS_REJECTED_MESSAGE) from None

    def integration_from_keys(self) -> model.Integration:
        from products.workflows.backend.facade.api import (
            get_twilio_account_info,  # noqa: PLC0415 — keeps the workflows facade off the model import path
        )
        from products.workflows.backend.facade.contracts import TwilioCredentialsRejected  # noqa: PLC0415

        try:
            account_info = get_twilio_account_info(account_sid=self._account_sid, auth_token=self._auth_token)
        except TwilioCredentialsRejected:
            raise ValidationError(CREDENTIALS_REJECTED_MESSAGE) from None

        if not account_info.get("sid"):
            raise ValidationError({"account_info": "Failed to get account info"})

        integration, created = model.Integration.objects.update_or_create(
            team_id=self.integration.team_id,
            kind="twilio",
            integration_id=account_info["sid"],
            defaults={
                "config": {
                    "account_sid": account_info["sid"],
                },
                "sensitive_config": {
                    "auth_token": self.integration.sensitive_config["auth_token"],
                },
                "created_by_id": self.integration.created_by_id,
                "errors": "",
            },
        )

        return integration
