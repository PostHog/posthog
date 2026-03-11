import uuid

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import ProxyRecord
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.temporal.proxy_service.common import SendProxyCreatedEmailInputs, activity_send_proxy_created_email


def _make_inputs(**overrides):
    defaults = {
        "organization_id": uuid.uuid4(),
        "proxy_record_id": uuid.uuid4(),
        "domain": "proxy.example.com",
    }
    defaults.update(overrides)
    return SendProxyCreatedEmailInputs(**defaults)  # type: ignore


@pytest.mark.django_db(transaction=True)
class TestSendProxyCreatedEmail:
    def test_sends_email_when_record_and_user_exist(self):
        org = Organization.objects.create(name="Test Org")
        user = User.objects.create_and_join(org, "admin@example.com", "password", first_name="Alice")
        proxy = ProxyRecord.objects.create(
            organization=org,
            domain="proxy.example.com",
            target_cname="target.example.com",
            created_by=user,
        )

        inputs = _make_inputs(organization_id=org.id, proxy_record_id=proxy.id)

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as MockEmailMessage,
        ):
            mock_instance = MagicMock()
            MockEmailMessage.return_value = mock_instance

            activity_send_proxy_created_email(inputs)

            MockEmailMessage.assert_called_once()
            call_kwargs = MockEmailMessage.call_args[1]
            assert call_kwargs["template_name"] == "proxy_provisioned"
            assert call_kwargs["use_http"] is True
            assert call_kwargs["campaign_key"] == f"proxy_provisioned_{proxy.id}"
            assert call_kwargs["template_context"]["domain"] == "proxy.example.com"
            assert call_kwargs["template_context"]["user_name"] == "Alice"
            mock_instance.add_user_recipient.assert_called_once_with(user)
            mock_instance.send.assert_called_once_with(send_async=True)

    def test_does_not_send_when_record_missing(self):
        inputs = _make_inputs(proxy_record_id=uuid.uuid4())

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as MockEmailMessage,
        ):
            activity_send_proxy_created_email(inputs)
            MockEmailMessage.assert_not_called()

    def test_does_not_send_when_created_by_is_null(self):
        org = Organization.objects.create(name="Test Org")
        proxy = ProxyRecord.objects.create(
            organization=org,
            domain="proxy.example.com",
            target_cname="target.example.com",
            created_by=None,
        )

        inputs = _make_inputs(organization_id=org.id, proxy_record_id=proxy.id)

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as MockEmailMessage,
        ):
            activity_send_proxy_created_email(inputs)
            MockEmailMessage.assert_not_called()

    def test_does_not_send_when_email_unavailable(self):
        org = Organization.objects.create(name="Test Org")
        user = User.objects.create_and_join(org, "admin@example.com", "password", first_name="Alice")
        proxy = ProxyRecord.objects.create(
            organization=org,
            domain="proxy.example.com",
            target_cname="target.example.com",
            created_by=user,
        )

        inputs = _make_inputs(organization_id=org.id, proxy_record_id=proxy.id)

        with patch("posthog.email.is_email_available", return_value=False):
            with patch("posthog.email.EmailMessage") as MockEmailMessage:
                activity_send_proxy_created_email(inputs)
                MockEmailMessage.assert_not_called()

    def test_swallows_exceptions_without_raising(self):
        inputs = _make_inputs()

        with patch("posthog.email.is_email_available", side_effect=Exception("boom")):
            # Should not raise
            activity_send_proxy_created_email(inputs)
