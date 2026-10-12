from typing import cast

import pytest
from unittest.mock import MagicMock, call, patch

from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from products.alerts_platform.backend.delivery.email import TEMPLATE_NAME, EmailTransport
from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import AlertDestinationData, AlertEventKind
from products.alerts_platform.backend.tests.delivery_messages import alert_message, announced_transition

TARGET = cast(AlertDestinationData, {"type": "email", "email_addresses": ["first@example.com", "second@example.com"]})


class TestEmailTransport(SimpleTestCase):
    def _deliver(
        self, kind: AlertEventKind = AlertEventKind.FIRING, headline: str = "API errors is firing"
    ) -> MagicMock:
        message = alert_message(
            headline=headline,
            details=(MessageDetail(label="Value", value="312"),),
            transition=announced_transition(kind),
        )
        with patch("products.alerts_platform.backend.delivery.email.EmailMessage") as email_message:
            handle = EmailTransport().deliver(team_id=2, target=TARGET, message=message)
        assert handle is None
        return email_message

    def test_one_email_reaches_every_subscriber(self) -> None:
        email_message = self._deliver(headline="API errors\nis firing")

        kwargs = email_message.call_args.kwargs
        assert kwargs["template_name"] == TEMPLATE_NAME
        assert kwargs["subject"] == "PostHog alert: API errors is firing"
        assert email_message.return_value.add_recipient.call_args_list == [
            call(email="first@example.com"),
            call(email="second@example.com"),
        ]
        email_message.return_value.send.assert_called_once_with()

    def test_a_retry_reuses_the_campaign_key_and_a_new_transition_does_not(self) -> None:
        def key(kind: AlertEventKind) -> str:
            return self._deliver(kind).call_args.kwargs["campaign_key"]

        # The campaign key is what stops a retried delivery emailing anyone a second copy.
        assert key(AlertEventKind.FIRING) == key(AlertEventKind.FIRING)
        assert key(AlertEventKind.FIRING) != key(AlertEventKind.RESOLVED)
        assert len(key(AlertEventKind.FIRING)) <= 128

    def test_a_destination_without_recipients_is_refused(self) -> None:
        with pytest.raises(DeliveryError):
            EmailTransport().deliver(
                team_id=2, target=cast(AlertDestinationData, {"type": "email"}), message=alert_message()
            )

    def test_an_instance_without_email_names_the_cause(self) -> None:
        with patch(
            "products.alerts_platform.backend.delivery.email.EmailMessage",
            side_effect=ImproperlyConfigured("Email is not enabled in this instance."),
        ):
            with pytest.raises(DeliveryError, match="not configured"):
                EmailTransport().deliver(team_id=2, target=TARGET, message=alert_message())

    def test_the_template_renders_the_headline_and_every_detail(self) -> None:
        html = render_to_string(
            f"email/{TEMPLATE_NAME}.html",
            {
                "headline": "API errors is firing",
                "details": [{"label": "Value", "value": "312"}, {"label": "Threshold", "value": "> 300"}],
            },
        )

        assert "API errors is firing" in html
        assert "Value:</strong> 312" in html
        assert "Threshold:</strong> &gt; 300" in html
