"""Twilio integration."""

from rest_framework.exceptions import ValidationError

from products.workflows.backend.providers import TwilioProvider

from . import model


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
        twilio_phone_numbers = self.twilio_provider.get_phone_numbers()

        if not twilio_phone_numbers:
            raise Exception(f"There was an internal error")

        return twilio_phone_numbers

    def integration_from_keys(self) -> model.Integration:
        account_info = self.twilio_provider.get_account_info()

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
                "created_by": self.integration.created_by,
            },
        )
        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration
