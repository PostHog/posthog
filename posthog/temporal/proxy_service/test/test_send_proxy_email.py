import uuid

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import ProxyRecord
from posthog.models.messaging import MessagingRecord
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.temporal.proxy_service.common import SendProxyCreatedEmailInputs, activity_send_proxy_created_email


@pytest.fixture(autouse=True)
def _no_temporal_worker_reconnect(monkeypatch):
    # The activity calls django.db.connection.connect() to recover from stale
    # worker connections in production. Under test that drops the test's
    # wrapping atomic transaction (and the freshly-opened connection can't see
    # data the test just wrote). Stub it out so tests can stay on fast
    # transaction-rollback isolation instead of needing transaction=True.
    from django.db import connection

    monkeypatch.setattr(connection, "connect", lambda: None)


def _make_inputs(**overrides):
    defaults = {
        "organization_id": uuid.uuid4(),
        "proxy_record_id": uuid.uuid4(),
        "domain": "proxy.example.com",
    }
    defaults.update(overrides)
    return SendProxyCreatedEmailInputs(**defaults)  # type: ignore


@pytest.fixture(autouse=True)
def monitor_schedule(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    schedule_exists = MagicMock(return_value=False)
    monkeypatch.setattr("posthog.temporal.proxy_service.common.schedule_exists", schedule_exists)
    monkeypatch.setattr("posthog.temporal.proxy_service.common.sync_connect", MagicMock())
    return schedule_exists


@pytest.mark.django_db
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

    @pytest.mark.parametrize("previous_provisioning", ["monitor_schedule", "prior_delivery", "unsent_delivery"])
    def test_creation_email_after_recovery(self, previous_provisioning: str, monitor_schedule: MagicMock) -> None:
        org = Organization.objects.create(name="Test Org")
        user = User.objects.create_and_join(org, "new-address@example.com", "password")
        proxy = ProxyRecord.objects.create(
            organization=org,
            domain="proxy.example.com",
            target_cname="target.example.com",
            created_by=user,
            status=ProxyRecord.Status.VALID,
        )
        if previous_provisioning == "monitor_schedule":
            monitor_schedule.side_effect = lambda _, schedule_id: schedule_id == f"monitor-proxy-{proxy.id}"
        else:
            MessagingRecord.objects.create(
                email_hash="previous-email-hash",
                campaign_key=f"proxy_provisioned_{proxy.id}",
                sent_at=timezone.now() if previous_provisioning == "prior_delivery" else None,
            )

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email._send_email.apply_async") as enqueue_email,
        ):
            activity_send_proxy_created_email(_make_inputs(organization_id=org.id, proxy_record_id=proxy.id))

        assert enqueue_email.called == (previous_provisioning == "unsent_delivery")

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
