"""Twilio integration."""

from rest_framework.exceptions import ErrorDetail, ValidationError

from products.workflows.backend.providers import TwilioCredentialsRejectedError, TwilioProvider

from . import model

# Twilio does not tell us which of the two keys is wrong, so the message points at both.
CREDENTIALS_REJECTED_MESSAGE = "Twilio rejected these keys. Check your Account SID and auth token, then try again."
# Stable machine code for a handled credential rejection. The frontend keeps this out of error
# tracking, since the setup modal and phone-number picker already show it to the user. Keep in sync
# with HANDLED_VALIDATION_CODES in frontend/src/lib/api-error.ts.
CREDENTIALS_REJECTED_CODE = "twilio_credentials_rejected"


def _credentials_rejected_error() -> ValidationError:
    # Keyed on "accountSid", the field the setup modal renders.
    return ValidationError({"accountSid": ErrorDetail(CREDENTIALS_REJECTED_MESSAGE, code=CREDENTIALS_REJECTED_CODE)})


class TwilioIntegration:
    integration: model.Integration
    twilio_provider: TwilioProvider

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "twilio":
            raise Exception("TwilioIntegration init called with Integration with wrong 'kind'")
        self.integration = integration
        self.twilio_provider = TwilioProvider(
            account_sid=self.integration.config["account_sid"],
            auth_token=self.integration.sensitive_config["auth_token"],
        )

    def list_twilio_phone_numbers(self) -> list[dict]:
        try:
            return self.twilio_provider.get_phone_numbers()
        except TwilioCredentialsRejectedError:
            raise _credentials_rejected_error()

    def integration_from_keys(self) -> model.Integration:
        try:
            account_info = self.twilio_provider.get_account_info()
        except TwilioCredentialsRejectedError:
            raise _credentials_rejected_error()

        if not account_info.get("sid"):
            raise _credentials_rejected_error()

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
                "created_by": self.integration.created_by,
            },
        )
        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration
