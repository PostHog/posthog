"""Twilio integration."""

from rest_framework.exceptions import ValidationError

from products.workflows.backend.providers import TwilioCredentialsRejectedError, TwilioProvider

from . import model

# Twilio does not tell us which of the two keys is wrong, so the message points at both.
CREDENTIALS_REJECTED_MESSAGE = "Twilio rejected these keys. Check your Account SID and auth token, then try again."


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
            raise ValidationError({"accountSid": CREDENTIALS_REJECTED_MESSAGE})

    def integration_from_keys(self) -> model.Integration:
        try:
            account_info = self.twilio_provider.get_account_info()
        except TwilioCredentialsRejectedError:
            raise ValidationError({"accountSid": CREDENTIALS_REJECTED_MESSAGE})

        if not account_info.get("sid"):
            raise ValidationError({"accountSid": CREDENTIALS_REJECTED_MESSAGE})

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
