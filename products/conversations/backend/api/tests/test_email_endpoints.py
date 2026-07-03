from datetime import timedelta
from io import BytesIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from parameterized import parameterized
from PIL import Image

from posthog.models.comment import Comment
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team

from products.conversations.backend.mailgun import (
    MailgunDomainConflict,
    MailgunDomainNotRegistered,
    MailgunNotConfigured,
    MailgunPermanentError,
    MailgunTransientError,
)
from products.conversations.backend.models import EmailChannel, EmailOutboxMessage
from products.conversations.backend.models.ticket import Ticket


def _make_png_bytes() -> bytes:
    """Generate a minimal valid 1x1 PNG."""
    buf = BytesIO()
    Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
    return buf.getvalue()


class TestEmailConnectDomainCaseInsensitivity(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_connect_lowercases_domain(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        response = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "Support@Example.COM", "from_name": "Support"},
            content_type="application/json",
        )

        assert response.status_code == 200
        config = EmailChannel.objects.get(team=self.team)
        assert config.from_email == "support@example.com"
        assert config.domain == "example.com"

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_connect_rejects_duplicate_domain_different_casing_cross_org(
        self, _mock_setting: MagicMock, _mock_mailgun: MagicMock
    ):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )

        # A team in a different org tries the same domain with different casing
        other_org = Organization.objects.create(name="Other Org")
        second_team = Team.objects.create(organization=other_org)
        OrganizationMembership.objects.create(
            user=self.user, organization=other_org, level=OrganizationMembership.Level.ADMIN
        )
        self.user.current_team = second_team
        self.user.save()

        response = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "help@Example.COM", "from_name": "Help"},
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "already in use" in response.json()["error"]


class TestEmailChannelPermissions(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    @parameterized.expand(
        [
            (
                "connect",
                "post",
                "/api/conversations/v1/email/connect",
                {"from_email": "s@example.com", "from_name": "S"},
            ),
            (
                "disconnect",
                "post",
                "/api/conversations/v1/email/disconnect",
                {"config_id": "00000000-0000-0000-0000-000000000999"},
            ),
        ]
    )
    def test_member_cannot_access(self, _name, method, path, body):
        response = getattr(self.client, method)(path, body, content_type="application/json")
        assert response.status_code == 403

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_admin_can_connect_email(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "s@example.com", "from_name": "S"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_admin_can_disconnect_email(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Disconnect with a nonexistent config_id returns 404 (not crash)
        response = self.client.post(
            "/api/conversations/v1/email/disconnect",
            {"config_id": "00000000-0000-0000-0000-000000000999"},
            content_type="application/json",
        )
        assert response.status_code == 404


class TestEmailMultiConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.force_login(self.user)

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_connect_multiple_emails(self, _mock_setting: MagicMock, mock_mailgun: MagicMock):
        r1 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        assert r1.status_code == 200

        r2 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )
        assert r2.status_code == 200

        configs = EmailChannel.objects.filter(team=self.team)
        assert configs.count() == 2

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_same_domain_skips_mailgun_add(self, _mock_setting: MagicMock, mock_mailgun: MagicMock):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        mock_mailgun.reset_mock()

        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )
        # Mailgun add_domain NOT called for second email on same domain
        mock_mailgun.assert_not_called()

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_reject_duplicate_from_email(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        r2 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support Again"},
            content_type="application/json",
        )
        assert r2.status_code == 409

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_same_org_different_team_domain_allowed(self, _mock_setting: MagicMock, mock_mailgun: MagicMock):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        mock_mailgun.reset_mock()

        second_team = Team.objects.create(organization=self.organization)
        self.user.current_team = second_team
        self.user.save()

        r2 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )
        assert r2.status_code == 200
        # Reuses existing Mailgun registration — no second add_domain call
        mock_mailgun.assert_not_called()

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_cross_org_domain_rejected(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )

        other_org = Organization.objects.create(name="Other Org")
        second_team = Team.objects.create(organization=other_org)
        OrganizationMembership.objects.create(
            user=self.user, organization=other_org, level=OrganizationMembership.Level.ADMIN
        )
        self.user.current_team = second_team
        self.user.save()

        r2 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )
        assert r2.status_code == 409
        assert "another organization" in r2.json()["error"]

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch("products.conversations.backend.api.email_settings.mailgun_delete_domain")
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_disconnect_one_keeps_email_enabled(
        self, _mock_setting: MagicMock, _mock_delete: MagicMock, _mock_add: MagicMock
    ):
        r1 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )

        config1_id = r1.json()["config"]["id"]

        response = self.client.post(
            "/api/conversations/v1/email/disconnect",
            {"config_id": config1_id},
            content_type="application/json",
        )
        assert response.status_code == 200

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings.get("email_enabled") is True
        assert EmailChannel.objects.filter(team=self.team).count() == 1

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch("products.conversations.backend.api.email_settings.mailgun_delete_domain")
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_disconnect_last_disables_email(
        self, _mock_setting: MagicMock, _mock_delete: MagicMock, _mock_add: MagicMock
    ):
        r1 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        config_id = r1.json()["config"]["id"]

        self.client.post(
            "/api/conversations/v1/email/disconnect",
            {"config_id": config_id},
            content_type="application/json",
        )

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings.get("email_enabled") is False

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch("products.conversations.backend.api.email_settings.mailgun_delete_domain")
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_disconnect_keeps_domain_if_sibling_exists(
        self, _mock_setting: MagicMock, mock_delete: MagicMock, _mock_add: MagicMock
    ):
        r1 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )

        config1_id = r1.json()["config"]["id"]
        self.client.post(
            "/api/conversations/v1/email/disconnect",
            {"config_id": config1_id},
            content_type="application/json",
        )

        # Domain NOT deleted from Mailgun since billing@ still uses it
        mock_delete.assert_not_called()

    @patch(
        "products.conversations.backend.api.email_settings.mailgun_add_domain",
        side_effect=MailgunDomainConflict("Domain example.com already exists"),
    )
    @patch("products.conversations.backend.api.email_settings.mailgun_delete_domain")
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_connect_rejects_preexisting_mailgun_domain(
        self,
        _mock_setting: MagicMock,
        mock_mailgun_delete: MagicMock,
        _mock_mailgun_add: MagicMock,
    ):
        response = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert EmailChannel.objects.filter(team=self.team).count() == 0
        mock_mailgun_delete.assert_not_called()

        self.team.refresh_from_db()
        settings = self.team.conversations_settings or {}
        assert settings.get("email_enabled") is not True

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_status_returns_all_configs(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )

        response = self.client.get("/api/conversations/v1/email/status")
        assert response.status_code == 200
        data = response.json()
        assert len(data["configs"]) == 2
        emails = {c["from_email"] for c in data["configs"]}
        assert emails == {"support@example.com", "billing@example.com"}

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_config_limit_enforced(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        from products.conversations.backend.models.team_conversations_email_config import MAX_EMAIL_CONFIGS_PER_TEAM

        for i in range(MAX_EMAIL_CONFIGS_PER_TEAM):
            r = self.client.post(
                "/api/conversations/v1/email/connect",
                {"from_email": f"addr{i}@example{i}.com", "from_name": f"Name {i}"},
                content_type="application/json",
            )
            assert r.status_code == 200, f"Failed to connect config {i}: {r.json()}"

        r = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "overflow@overflow.com", "from_name": "Overflow"},
            content_type="application/json",
        )
        assert r.status_code == 400
        assert "Maximum" in r.json()["error"]

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_idor_disconnect_other_teams_config(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        r1 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@team1.com", "from_name": "Team1"},
            content_type="application/json",
        )
        config_id = r1.json()["config"]["id"]

        second_team = Team.objects.create(organization=self.organization)
        self.user.current_team = second_team
        self.user.save()

        response = self.client.post(
            "/api/conversations/v1/email/disconnect",
            {"config_id": config_id},
            content_type="application/json",
        )
        assert response.status_code == 404

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.mailgun_verify_domain",
        return_value={"state": "active", "sending_dns_records": []},
    )
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_verify_domain_updates_all_siblings(
        self, _mock_setting: MagicMock, _mock_verify: MagicMock, _mock_add: MagicMock
    ):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )
        r2 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )

        # Also connect on a different team in the same org
        second_team = Team.objects.create(organization=self.organization)
        self.user.current_team = second_team
        self.user.save()
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "sales@example.com", "from_name": "Sales"},
            content_type="application/json",
        )

        # Switch back to original team to verify
        self.user.current_team = self.team
        self.user.save()

        config2_id = r2.json()["config"]["id"]
        response = self.client.post(
            "/api/conversations/v1/email/verify-domain",
            {"config_id": config2_id},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["domain_verified"] is True

        # All configs across the org sharing the domain should be verified
        configs = EmailChannel.objects.filter(team__organization_id=self.organization.id, domain="example.com")
        assert configs.count() == 3
        assert all(c.domain_verified for c in configs)

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.mailgun_verify_domain",
        return_value={"state": "active", "sending_dns_records": []},
    )
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_idor_verify_other_teams_config(
        self, _mock_setting: MagicMock, _mock_verify: MagicMock, _mock_add: MagicMock
    ):
        r1 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@team1.com", "from_name": "Team1"},
            content_type="application/json",
        )
        config_id = r1.json()["config"]["id"]

        second_team = Team.objects.create(organization=self.organization)
        self.user.current_team = second_team
        self.user.save()

        response = self.client.post(
            "/api/conversations/v1/email/verify-domain",
            {"config_id": config_id},
            content_type="application/json",
        )
        assert response.status_code == 404


class TestEmailInboundRegionRouting(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def _post(self, data: dict[str, str]):
        return self.client.post("/api/conversations/v1/email/inbound", data=data)

    @patch("products.conversations.backend.api.email_events.proxy_to_secondary_region", return_value=True)
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    @patch("products.conversations.backend.api.email_events.is_primary_region", return_value=True)
    def test_proxies_to_secondary_when_token_not_found_on_primary(
        self, _mock_region: MagicMock, _mock_sig: MagicMock, mock_proxy: MagicMock
    ):
        response = self._post({"recipient": "team-deadbeef@mg.posthog.com"})

        assert response.status_code == 200
        mock_proxy.assert_called_once()

    @patch("products.conversations.backend.api.email_events.proxy_to_secondary_region", return_value=False)
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    @patch("products.conversations.backend.api.email_events.is_primary_region", return_value=True)
    def test_returns_502_when_proxy_fails(self, _mock_region: MagicMock, _mock_sig: MagicMock, mock_proxy: MagicMock):
        response = self._post({"recipient": "team-deadbeef@mg.posthog.com"})

        assert response.status_code == 502
        mock_proxy.assert_called_once()

    @patch("products.conversations.backend.api.email_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    @patch("products.conversations.backend.api.email_events.is_primary_region", return_value=False)
    def test_returns_404_when_token_not_found_on_secondary(
        self, _mock_region: MagicMock, _mock_sig: MagicMock, mock_proxy: MagicMock
    ):
        response = self._post({"recipient": "team-deadbeef@mg.posthog.com"})

        assert response.status_code == 404
        mock_proxy.assert_not_called()


class TestBuildProxyKwargs(BaseTest):
    """Unit tests for _build_proxy_kwargs multipart fallback."""

    def test_raw_body_available(self):
        from django.test import RequestFactory

        from products.conversations.backend.services.region_routing import _build_proxy_kwargs

        factory = RequestFactory()
        request = factory.post(
            "/api/conversations/v1/email/inbound",
            data=b"key=val",
            content_type="application/x-www-form-urlencoded",
        )
        result = _build_proxy_kwargs(request, {"Content-Type": "application/x-www-form-urlencoded"})
        assert "data" in result
        assert "files" not in result
        assert result["data"] == b"key=val"

    def test_multipart_fallback_after_stream_consumed(self):
        from unittest.mock import PropertyMock, patch

        from django.http.request import RawPostDataException
        from django.test import RequestFactory

        from products.conversations.backend.services.region_routing import _build_proxy_kwargs

        factory = RequestFactory()
        png = SimpleUploadedFile("photo.png", _make_png_bytes(), content_type="image/png")
        request = factory.post(
            "/api/conversations/v1/email/inbound",
            data={"recipient": "team-abc@mg.posthog.com", "attachment-1": png},
        )

        _ = request.POST
        _ = request.FILES

        headers = {"Content-Type": "multipart/form-data; boundary=xxx"}
        with patch.object(type(request), "body", new_callable=PropertyMock, side_effect=RawPostDataException()):
            result = _build_proxy_kwargs(request, headers)

        assert "files" in result
        assert len(result["files"]) == 1
        key, (name, content_bytes, ct) = result["files"][0]
        assert key == "attachment-1"
        assert name == "photo.png"
        assert ct == "image/png"
        assert len(content_bytes) > 0

        assert any(k == "recipient" and v == "team-abc@mg.posthog.com" for k, v in result["data"])
        assert "content-type" not in {k.lower() for k in result["headers"]}


class TestEmailInboundMultiConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        # Enable email on team
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()

    def _create_config(self, from_email: str, token: str) -> EmailChannel:
        return EmailChannel.objects.create(
            team=self.team,
            inbound_token=token,
            from_email=from_email,
            from_name="Test",
            domain=from_email.split("@")[1],
            domain_verified=True,
        )

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_routes_to_correct_config(self, _mock_sig: MagicMock):
        config1 = self._create_config("support@example.com", "aaa111")
        self._create_config("billing@example.com", "bbb222")

        response = self.client.post(
            "/api/conversations/v1/email/inbound",
            {
                "recipient": "team-aaa111@mg.posthog.com",
                "from": "customer@test.com",
                "Message-Id": "<msg1@test.com>",
                "subject": "Help",
                "stripped-text": "I need help",
            },
        )
        assert response.status_code == 200

        ticket = Ticket.objects.get(team=self.team)
        assert ticket.email_config_id == config1.id
        assert ticket.email_from == "customer@test.com"

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_routes_to_second_config(self, _mock_sig: MagicMock):
        self._create_config("support@example.com", "aaa111")
        config2 = self._create_config("billing@example.com", "bbb222")

        response = self.client.post(
            "/api/conversations/v1/email/inbound",
            {
                "recipient": "team-bbb222@mg.posthog.com",
                "from": "vendor@test.com",
                "Message-Id": "<msg2@test.com>",
                "subject": "Invoice",
                "stripped-text": "Here is your invoice",
            },
        )
        assert response.status_code == 200

        ticket = Ticket.objects.get(team=self.team)
        assert ticket.email_config_id == config2.id


class TestSendEmailReplyMultiConfig(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()

    def _create_config(self, from_email: str, token: str, verified: bool = True) -> EmailChannel:
        return EmailChannel.objects.create(
            team=self.team,
            inbound_token=token,
            from_email=from_email,
            from_name="Test",
            domain=from_email.split("@")[1],
            domain_verified=verified,
        )

    def _create_ticket(self, config: EmailChannel | None) -> Ticket:
        from products.conversations.backend.models.constants import Channel, Status

        return Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            email_config=config,
            widget_session_id="",
            distinct_id="customer@test.com",
            status=Status.NEW,
            email_subject="Test",
            email_from="customer@test.com",
        )

    def _create_outbox(
        self, ticket: Ticket, content: str = "Reply from agent", rich_content: dict | None = None
    ) -> tuple[Comment, EmailOutboxMessage]:
        """Create the reply comment + its durable outbox row, mirroring the signal path."""
        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            rich_content=rich_content,
            created_by=self.user,
            item_context={"author_type": "support"},
        )
        # The post_save signal creates the outbox row when created_by is set; fall back
        # to creating it explicitly so the test is robust to signal gating changes.
        outbox = EmailOutboxMessage.objects.filter(comment=comment).first()
        if outbox is None:
            outbox = EmailOutboxMessage.objects.create(
                team=self.team,
                ticket=ticket,
                comment=comment,
                message_id="<test@mg.posthog.com>",
            )
        return comment, outbox

    def _run_reply(self, ticket: Ticket, content: str = "Reply from agent") -> tuple[Comment, EmailOutboxMessage]:
        from products.conversations.backend.tasks import send_email_reply

        comment, outbox = self._create_outbox(ticket, content=content)
        send_email_reply(str(outbox.id))
        outbox.refresh_from_db()
        return comment, outbox

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_uses_ticket_config(self, mock_send_mime: MagicMock):
        config1 = self._create_config("support@example.com", "aaa111")
        self._create_config("billing@example.com", "bbb222")
        ticket = self._create_ticket(config1)
        ticket.cc_participants = ["cc1@example.com", "cc2@example.com"]
        ticket.save(update_fields=["cc_participants"])

        _, outbox = self._run_reply(ticket)

        mock_send_mime.assert_called_once()
        args, kwargs = mock_send_mime.call_args

        # Regression guard: must use the ticket's domain, not a shared/global one.
        assert args[0] == "example.com"

        # Recipients include the customer and every CC participant.
        assert kwargs["recipients"] == ["customer@test.com", "cc1@example.com", "cc2@example.com"]

        # MIME body carries the From header with the config's from_email.
        # Separate substring checks avoid formataddr quoting flakes.
        mime_bytes = args[1]
        assert b"From: " in mime_bytes
        assert b"support@example.com" in mime_bytes

        # Guard against someone dropping linesep="\r\n" from the as_bytes() call.
        # RFC 5322 wants CRLF; Django's default is LF-only.
        assert b"\r\n" in mime_bytes

        assert outbox.status == EmailOutboxMessage.Status.SENT
        assert outbox.sent_at is not None

    @parameterized.expand(
        [
            # name, error raised by send_mime, whether it flips the domain back to unverified
            ("permanent_error", MailgunPermanentError("bad recipient"), False),
            ("not_configured", MailgunNotConfigured("mailgun not configured"), False),
            ("domain_not_registered", MailgunDomainNotRegistered("gone from mailgun"), True),
        ]
    )
    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_terminal_errors_mark_failed(
        self, _name: str, error: Exception, flips_domain_verified: bool, mock_send_mime: MagicMock
    ):
        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)

        mock_send_mime.side_effect = error

        _, outbox = self._run_reply(ticket)

        # One attempt, no retry, terminal failure recorded.
        assert mock_send_mime.call_count == 1
        assert outbox.status == EmailOutboxMessage.Status.FAILED_PERMANENT

        config.refresh_from_db()
        assert config.domain_verified is (not flips_domain_verified)

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_delivers_to_team_member_ticket(self, mock_send_mime: MagicMock):
        """An in-app agent reply on a ticket opened by a team member (e.g. dogfooding
        the support inbox) must still be delivered to them."""
        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)
        ticket.email_from = self.user.email
        ticket.save(update_fields=["email_from"])

        _, outbox = self._run_reply(ticket)

        mock_send_mime.assert_called_once()
        assert mock_send_mime.call_args[1]["recipients"] == [self.user.email]
        assert outbox.status == EmailOutboxMessage.Status.SENT

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_skips_comment_from_inbound_email(self, mock_send_mime: MagicMock):
        """Last-mile echo guard: an outbox row pointing at a comment that itself arrived
        via inbound email must never be sent, even if a regression enqueues one."""
        from products.conversations.backend.tasks import send_email_reply

        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)
        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Inbound team-member email",
            created_by=self.user,
            item_context={"author_type": "support", "from_email": True},
        )
        # The signal guard skips outbox creation; create the row explicitly to
        # simulate a regression in enqueueing.
        outbox = EmailOutboxMessage.objects.create(
            team=self.team,
            ticket=ticket,
            comment=comment,
            message_id="<echo-guard@mg.posthog.com>",
        )

        send_email_reply(str(outbox.id))
        outbox.refresh_from_db()

        mock_send_mime.assert_not_called()
        assert outbox.status == EmailOutboxMessage.Status.FAILED_PERMANENT
        assert outbox.last_error == "comment originated from inbound email"

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_transient_error_schedules_retry(self, mock_send_mime: MagicMock):
        """Transient errors must NOT be dropped or raised — the row stays pending with a
        backed-off next_attempt_at so the sweeper re-drives it. This is what survives a
        multi-day provider outage."""
        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)

        mock_send_mime.side_effect = MailgunTransientError("mailgun 503")

        before = timezone.now()
        _, outbox = self._run_reply(ticket, content="Reply")

        assert mock_send_mime.call_count == 1
        assert outbox.status == EmailOutboxMessage.Status.PENDING
        assert outbox.attempts == 1
        assert outbox.next_attempt_at > before
        assert outbox.locked_until is None

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_reuses_message_id_across_attempts(self, mock_send_mime: MagicMock):
        """A retried send must reuse the same Message-ID so threading/dedup stay stable."""
        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)

        # First attempt fails transiently.
        mock_send_mime.side_effect = MailgunTransientError("mailgun 503")
        _, outbox = self._run_reply(ticket, content="Reply")
        original_message_id = outbox.message_id

        # Make it due again and let the next attempt succeed.
        from products.conversations.backend.tasks import send_email_reply

        EmailOutboxMessage.objects.filter(id=outbox.id).update(next_attempt_at=timezone.now(), locked_until=None)
        mock_send_mime.side_effect = None
        send_email_reply(str(outbox.id))

        outbox.refresh_from_db()
        assert outbox.status == EmailOutboxMessage.Status.SENT
        assert outbox.message_id == original_message_id
        # Both attempts carried the same Message-ID header.
        first_mime = mock_send_mime.call_args_list[0].args[1]
        second_mime = mock_send_mime.call_args_list[1].args[1]
        assert original_message_id.encode() in first_mime
        assert original_message_id.encode() in second_mime

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_idempotent_when_already_sent(self, mock_send_mime: MagicMock):
        from products.conversations.backend.tasks import send_email_reply

        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)
        _, outbox = self._create_outbox(ticket)
        EmailOutboxMessage.objects.filter(id=outbox.id).update(status=EmailOutboxMessage.Status.SENT)

        send_email_reply(str(outbox.id))

        mock_send_mime.assert_not_called()

    @patch("products.conversations.backend.tasks.send_mime")
    def test_send_email_reply_marks_failed_when_no_config(self, mock_send_mime: MagicMock):
        ticket = self._create_ticket(None)

        _, outbox = self._run_reply(ticket, content="Reply")

        assert outbox.status == EmailOutboxMessage.Status.FAILED_PERMANENT
        mock_send_mime.assert_not_called()

    def test_outbox_row_created_in_signal_survives_without_broker(self):
        """The durable outbox row is created in the comment's transaction, so a reply is
        recoverable even if the broker never picks up the immediate send task."""
        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)

        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Reply",
            created_by=self.user,
            item_context={"author_type": "support"},
        )

        outbox = EmailOutboxMessage.objects.filter(comment=comment).first()
        assert outbox is not None
        assert outbox.status == EmailOutboxMessage.Status.PENDING
        assert outbox.message_id

    @parameterized.expand(
        [
            # name, scenario, expect send_mime called, resulting status
            ("due_row_is_sent", "due", True, EmailOutboxMessage.Status.SENT),
            ("locked_row_is_skipped", "locked", False, EmailOutboxMessage.Status.PENDING),
            ("expired_row_is_given_up", "expired", False, EmailOutboxMessage.Status.FAILED_PERMANENT),
        ]
    )
    @patch("products.conversations.backend.tasks.send_mime")
    def test_flush_pending_email_replies(
        self, _name: str, scenario: str, expect_send: bool, expected_status: str, mock_send_mime: MagicMock
    ):
        from products.conversations.backend.tasks import EMAIL_OUTBOX_MAX_AGE, flush_pending_email_replies

        config = self._create_config("support@example.com", "aaa111")
        ticket = self._create_ticket(config)
        _, outbox = self._create_outbox(ticket)

        now = timezone.now()
        if scenario == "locked":
            EmailOutboxMessage.objects.filter(id=outbox.id).update(locked_until=now + timedelta(minutes=5))
        elif scenario == "expired":
            EmailOutboxMessage.objects.filter(id=outbox.id).update(
                created_at=now - EMAIL_OUTBOX_MAX_AGE - timedelta(hours=1), next_attempt_at=now
            )

        flush_pending_email_replies()

        outbox.refresh_from_db()
        assert mock_send_mime.called is expect_send
        assert outbox.status == expected_status


class TestEmailInboundDmarcRewrite(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="dd00aa11cc2233ee",
            from_email="merch@posthog.com",
            from_name="Merch",
            domain="posthog.com",
            domain_verified=True,
        )

    def _base_data(self, msg_id: str) -> dict[str, str]:
        return {
            "recipient": "team-dd00aa11cc2233ee@mg.posthog.com",
            "Message-Id": msg_id,
            "subject": "Order question",
            "stripped-text": "Where is my order?",
        }

    @parameterized.expand(
        [
            (
                "x_original_from",
                {
                    "from": "'Alex Smith' via Merch <merch@posthog.com>",
                    "X-Original-From": "Alex Smith <alex@strictdmarc.com>",
                },
                "alex@strictdmarc.com",
                "Alex Smith",
            ),
            (
                "x_original_sender",
                {"from": "'Bob' via Merch <merch@posthog.com>", "X-Original-Sender": "bob@company.io"},
                "bob@company.io",
                "bob",
            ),
            (
                "reply_to_with_name",
                {"from": "'Jane Doe' via Merch <merch@posthog.com>", "Reply-To": "Jane Doe <jane@strictdmarc.com>"},
                "jane@strictdmarc.com",
                "Jane Doe",
            ),
            (
                "reply_to_bare_email",
                {"from": "'Someone' via Merch <merch@posthog.com>", "Reply-To": "someone@example.org"},
                "someone@example.org",
                "someone",
            ),
            (
                "x_original_from_over_reply_to",
                {
                    "from": "'Charlie' via Merch <merch@posthog.com>",
                    "X-Original-From": "Charlie <charlie@real.com>",
                    "Reply-To": "charlie-alt@other.com",
                },
                "charlie@real.com",
                "Charlie",
            ),
            (
                "no_recovery_headers_strips_via",
                {"from": "'Alex Smith' via Merch <merch@posthog.com>"},
                "merch@posthog.com",
                "Alex Smith",
            ),
            (
                "reply_to_matching_config_falls_through",
                {"from": "'Alice' via Merch <merch@posthog.com>", "Reply-To": "merch@posthog.com"},
                "merch@posthog.com",
                "Alice",
            ),
            (
                "non_rewritten_from_unchanged",
                {"from": "Regular User <regular@gmail.com>"},
                "regular@gmail.com",
                "Regular User",
            ),
            (
                "forged_from_no_via_skips_recovery",
                {"from": "Attacker <merch@posthog.com>", "X-Original-From": "attacker@evil.com"},
                "merch@posthog.com",
                "Attacker",
            ),
            (
                "malformed_x_original_from_rejected",
                {"from": "'Eve' via Merch <merch@posthog.com>", "X-Original-From": "not-an-email"},
                "merch@posthog.com",
                "Eve",
            ),
            (
                "malformed_reply_to_rejected",
                {"from": "'Eve' via Merch <merch@posthog.com>", "Reply-To": "bad@"},
                "merch@posthog.com",
                "Eve",
            ),
        ]
    )
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_dmarc_sender_recovery(self, _name, extra_headers, expected_email, expected_name, _mock_sig):
        data = self._base_data(f"<dmarc-{_name}@test.com>")
        data.update(extra_headers)
        self.client.post("/api/conversations/v1/email/inbound", data)

        ticket = Ticket.objects.get(team=self.team)
        assert ticket.email_from == expected_email
        assert ticket.anonymous_traits["email"] == expected_email
        assert ticket.anonymous_traits["name"] == expected_name

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_recovered_sender_flows_to_comment_context(self, _mock_sig: MagicMock):
        data = self._base_data("<dmarc-ctx@test.com>")
        data["from"] = "'Alex Smith' via Merch <merch@posthog.com>"
        data["X-Original-From"] = "Alex Smith <alex@strictdmarc.com>"
        self.client.post("/api/conversations/v1/email/inbound", data)

        ticket = Ticket.objects.get(team=self.team)
        assert ticket.distinct_id == "alex@strictdmarc.com"

        comment = Comment.objects.get(team=self.team, scope="conversations_ticket")
        assert comment.item_context is not None
        assert comment.item_context["email_from"] == "alex@strictdmarc.com"
        assert comment.item_context["email_from_name"] == "Alex Smith"


class TestEmailInboundTeamMemberDetection(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="ab01cd23ef45",
            from_email="security@posthog.com",
            from_name="Security",
            domain="posthog.com",
            domain_verified=True,
        )

    def _post(self, data: dict[str, str]):
        return self.client.post("/api/conversations/v1/email/inbound", data)

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_team_member_reply_attribution_and_unread(self, _mock_sig: MagicMock):
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": "Customer <customer@external.com>",
                "Message-Id": "<init@external.com>",
                "subject": "Security question",
                "stripped-text": "Hello",
            }
        )
        ticket = Ticket.objects.get(team=self.team)
        assert ticket.email_from == "customer@external.com"
        assert ticket.unread_team_count == 1

        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "sender": self.user.email,
                "from": f"{self.user.first_name} <{self.user.email}>",
                "Message-Id": "<reply@team.com>",
                "In-Reply-To": "<init@external.com>",
                "stripped-text": "Looking into this",
                "X-Mailgun-Spf": "Pass",
            }
        )

        comments = Comment.objects.filter(team=self.team, scope="conversations_ticket").order_by("created_at")
        assert comments.count() == 2

        customer_comment = comments[0]
        assert customer_comment.item_context["author_type"] == "customer"
        assert customer_comment.created_by is None

        support_comment = comments[1]
        assert support_comment.item_context["author_type"] == "support"
        assert support_comment.created_by_id == self.user.id

        ticket.refresh_from_db()
        assert ticket.unread_team_count == 1

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_team_member_inbound_stamps_from_email_and_no_outbox(self, _mock_sig: MagicMock):
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": "Customer <customer@external.com>",
                "Message-Id": "<echo-init@external.com>",
                "subject": "Help please",
                "stripped-text": "Need help",
            }
        )
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "sender": self.user.email,
                "from": f"{self.user.first_name} <{self.user.email}>",
                "Message-Id": "<echo-reply@team.com>",
                "In-Reply-To": "<echo-init@external.com>",
                "stripped-text": "I will look into this",
                "X-Mailgun-Spf": "Pass",
            }
        )

        support_comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").order_by("created_at")[1]

        assert isinstance(support_comment.item_context, dict)
        assert support_comment.item_context["from_email"] is True
        assert support_comment.item_context["author_type"] == "support"
        assert EmailOutboxMessage.objects.filter(comment=support_comment).count() == 0

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_customer_inbound_stamps_from_email(self, _mock_sig: MagicMock):
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": "Customer <customer@external.com>",
                "Message-Id": "<cust-from@external.com>",
                "subject": "Question",
                "stripped-text": "Hello",
            }
        )

        comment = Comment.objects.get(team=self.team, scope="conversations_ticket")
        assert isinstance(comment.item_context, dict)
        assert comment.item_context["from_email"] is True
        assert comment.item_context["author_type"] == "customer"

    @parameterized.expand(
        [
            # (name, extra_post_fields, expected_identity_verified)
            ("spf_pass_aligned_domain", {"sender": "alice@external.com", "X-Mailgun-Spf": "Pass"}, True),
            ("no_spf", {}, False),
            ("spf_pass_misaligned_domain", {"sender": "alice@evil.com", "X-Mailgun-Spf": "Pass"}, False),
        ]
    )
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_identity_verified_reflects_spf(
        self, _name: str, extra_fields: dict[str, str], expected_verified: bool, _mock_sig: MagicMock
    ):
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": "Alice <alice@external.com>",
                "Message-Id": f"<iv-{_name}@external.com>",
                "subject": "Question",
                "stripped-text": "Hello",
                **extra_fields,
            }
        )
        ticket = Ticket.objects.get(team=self.team)
        assert ticket.identity_verified is expected_verified

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_no_spf_treated_as_customer(self, _mock_sig: MagicMock):
        """From header matches a team member but no SPF pass → customer."""
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": "Customer <customer@external.com>",
                "Message-Id": "<nospf-init@external.com>",
                "subject": "Question",
                "stripped-text": "Hello",
            }
        )
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "sender": self.user.email,
                "from": f"Forged <{self.user.email}>",
                "Message-Id": "<nospf-reply@external.com>",
                "In-Reply-To": "<nospf-init@external.com>",
                "stripped-text": "I am totally a team member",
            }
        )
        forged = Comment.objects.filter(team=self.team, scope="conversations_ticket").order_by("created_at")[1]
        assert forged.item_context["author_type"] == "customer"
        assert forged.created_by is None

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_spf_pass_but_mismatched_envelope_treated_as_customer(self, _mock_sig: MagicMock):
        """SPF passes but envelope sender domain != From domain → customer."""
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": "Customer <customer@external.com>",
                "Message-Id": "<align-init@external.com>",
                "subject": "Question",
                "stripped-text": "Hello",
            }
        )
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "sender": "attacker@evil.com",
                "from": f"Forged <{self.user.email}>",
                "Message-Id": "<align-reply@evil.com>",
                "In-Reply-To": "<align-init@external.com>",
                "stripped-text": "Cross-domain forgery attempt",
                "X-Mailgun-Spf": "Pass",
            }
        )
        forged = Comment.objects.filter(team=self.team, scope="conversations_ticket").order_by("created_at")[1]
        assert forged.item_context["author_type"] == "customer"
        assert forged.created_by is None

    @parameterized.expand(
        [
            # (name, claimed_email, reply_sender, expected_verified)
            # Same identity re-authenticates on a later message → legitimately promoted.
            ("matching_sender", "alice@external.com", "alice@external.com", True),
            # A different SPF-aligned sender threads onto a ticket claiming someone else's
            # identity — must NOT promote it to verified (confused-deputy / impersonation).
            ("different_sender", "victim@external.com", "attacker@evil.com", False),
        ]
    )
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_promotion_requires_authenticated_sender_to_match_ticket_identity(
        self, _name: str, claimed_email: str, reply_sender: str, expected_verified: bool, _mock_sig: MagicMock
    ):
        # First message: unauthenticated (no SPF) → unverified ticket claiming `claimed_email`.
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": f"Claimant <{claimed_email}>",
                "Message-Id": f"<promote-init-{_name}@external.com>",
                "subject": "Question",
                "stripped-text": "Hello",
            }
        )
        # Reply: SPF-authenticated (envelope sender aligned with From) threaded onto the same ticket.
        self._post(
            {
                "recipient": "team-ab01cd23ef45@mg.posthog.com",
                "from": f"Reply <{reply_sender}>",
                "sender": reply_sender,
                "X-Mailgun-Spf": "Pass",
                "Message-Id": f"<promote-reply-{_name}@external.com>",
                "In-Reply-To": f"<promote-init-{_name}@external.com>",
                "stripped-text": "Follow-up",
            }
        )
        ticket = Ticket.objects.get(team=self.team)
        assert ticket.identity_verified is expected_verified


class TestEmailInboundCcParticipants(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="cc00ee11ff22",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )

    def _base_data(self, msg_id: str) -> dict[str, str]:
        return {
            "recipient": "team-cc00ee11ff22@mg.posthog.com",
            "from": "sender@test.com",
            "Message-Id": msg_id,
            "subject": "Help",
            "stripped-text": "Need help",
        }

    @parameterized.expand(
        [
            ("with_display_names", "Dev <dev@company.com>, pm@company.com", ["dev@company.com", "pm@company.com"]),
            ("self_cc_filtered", "dev@company.com, team-cc00ee11ff22@mg.posthog.com", ["dev@company.com"]),
            ("no_cc_header", None, []),
        ]
    )
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_new_ticket_cc_participants(self, _name, cc_header, expected, _mock_sig):
        data = self._base_data(f"<cc-{_name}@test.com>")
        if cc_header:
            data["Cc"] = cc_header
        response = self.client.post("/api/conversations/v1/email/inbound", data)
        assert response.status_code == 200
        ticket = Ticket.objects.get(team=self.team)
        assert ticket.cc_participants == expected

    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_reply_merges_cc_participants(self, _mock_sig: MagicMock):
        data1 = self._base_data("<cc2@test.com>")
        data1["Cc"] = "dev@company.com"
        self.client.post("/api/conversations/v1/email/inbound", data1)

        ticket = Ticket.objects.get(team=self.team)
        assert ticket.cc_participants == ["dev@company.com"]

        data2 = self._base_data("<cc3@test.com>")
        data2["In-Reply-To"] = "<cc2@test.com>"
        data2["Cc"] = "dev@company.com, new@company.com"
        self.client.post("/api/conversations/v1/email/inbound", data2)

        ticket.refresh_from_db()
        assert ticket.cc_participants == ["dev@company.com", "new@company.com"]


class TestEmailInboundAttachments(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="aabbcc111222",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )

    def _base_post_data(self, msg_id: str = "<att@test.com>") -> dict:
        return {
            "recipient": "team-aabbcc111222@mg.posthog.com",
            "from": "sender@test.com",
            "Message-Id": msg_id,
            "subject": "With attachment",
            "stripped-text": "See attached",
        }

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_with_image_attachment(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        attachment = SimpleUploadedFile("photo.png", _make_png_bytes(), content_type="image/png")

        data = self._base_post_data("<img@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.post("/api/conversations/v1/email/inbound", {**data, "attachment-1": attachment})

        assert response.status_code == 200
        mock_storage.assert_called_once()

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert "![photo.png]" in comment.content
        assert comment.rich_content is not None
        image_nodes = [n for n in comment.rich_content["content"] if n["type"] == "image"]
        assert len(image_nodes) == 1
        assert image_nodes[0]["attrs"]["alt"] == "photo.png"
        assert comment.item_context["email_attachments"] is not None
        assert len(comment.item_context["email_attachments"]) == 1
        assert comment.item_context["email_attachments"][0]["content_type"] == "image/png"

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_with_non_image_attachment(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        pdf = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 fake content", content_type="application/pdf")

        data = self._base_post_data("<pdf@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.post("/api/conversations/v1/email/inbound", {**data, "attachment-1": pdf})

        assert response.status_code == 200

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert "[invoice.pdf]" in comment.content
        assert comment.rich_content is not None
        link_nodes = [
            n
            for n in comment.rich_content["content"]
            if n["type"] == "paragraph"
            and any(m.get("type") == "link" for child in n.get("content", []) for m in child.get("marks", []))
        ]
        assert len(link_nodes) == 1

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_with_multiple_attachments(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        png = SimpleUploadedFile("photo.png", _make_png_bytes(), content_type="image/png")
        pdf = SimpleUploadedFile("doc.pdf", b"%PDF-1.4 content", content_type="application/pdf")

        data = self._base_post_data("<multi@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.post(
                "/api/conversations/v1/email/inbound", {**data, "attachment-1": png, "attachment-2": pdf}
            )

        assert response.status_code == 200
        assert mock_storage.call_count == 2

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert comment.rich_content is not None
        assert len(comment.rich_content["content"]) == 3  # text paragraph + image + file link
        assert comment.item_context["email_attachments"] is not None
        assert len(comment.item_context["email_attachments"]) == 2

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.MAX_ATTACHMENT_SIZE", 100)
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_attachment_too_large_is_skipped(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        oversized = SimpleUploadedFile("big.bin", b"x" * 101, content_type="application/octet-stream")

        data = self._base_post_data("<huge@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.post("/api/conversations/v1/email/inbound", {**data, "attachment-1": oversized})

        assert response.status_code == 200
        mock_storage.assert_not_called()

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert comment.content == "See attached"
        assert comment.rich_content is None
        assert comment.item_context.get("email_attachments") is None

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_without_object_storage_skips_attachments(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        png = SimpleUploadedFile("photo.png", _make_png_bytes(), content_type="image/png")

        data = self._base_post_data("<nostorage@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=False):
            response = self.client.post("/api/conversations/v1/email/inbound", {**data, "attachment-1": png})

        assert response.status_code == 200
        mock_storage.assert_not_called()

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert comment.content == "See attached"
        assert comment.rich_content is None

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_invalid_image_is_rejected(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        fake_image = SimpleUploadedFile("evil.png", b"<html>not an image</html>", content_type="image/png")

        data = self._base_post_data("<evil@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.post("/api/conversations/v1/email/inbound", {**data, "attachment-1": fake_image})

        assert response.status_code == 200
        mock_storage.assert_not_called()

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert comment.content == "See attached"
        assert comment.rich_content is None

    @patch("products.conversations.backend.services.attachments.save_content_to_object_storage")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    def test_inbound_no_attachments_unchanged(self, _mock_sig: MagicMock, mock_storage: MagicMock):
        data = self._base_post_data("<plain@test.com>")
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            response = self.client.post("/api/conversations/v1/email/inbound", data)

        assert response.status_code == 200
        mock_storage.assert_not_called()

        comment = Comment.objects.filter(team=self.team, scope="conversations_ticket").first()
        assert comment is not None
        assert comment.content == "See attached"
        assert comment.rich_content is None
        assert comment.item_context.get("email_attachments") is None


class TestEmailSendTestView(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="send11test22",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )

    def _post(self) -> dict:
        return {"config_id": str(self.config.id)}

    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    @patch("products.conversations.backend.api.email_settings.send_mime")
    def test_success(self, mock_send_mime: MagicMock, _mock_setting: MagicMock):
        mock_send_mime.return_value = "<mg-id@example.com>"

        response = self.client.post(
            "/api/conversations/v1/email/send-test", self._post(), content_type="application/json"
        )

        assert response.status_code == 200
        mock_send_mime.assert_called_once()
        args, kwargs = mock_send_mime.call_args
        assert args[0] == "example.com"
        assert kwargs["recipients"] == [self.user.email]

    @parameterized.expand(
        [
            ("not_configured", "MailgunNotConfigured", "no api key", 500),
            ("domain_not_registered", "MailgunDomainNotRegistered", "gone", 502),
            ("permanent_error", "MailgunPermanentError", "bad recipient", 502),
        ]
    )
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    @patch("products.conversations.backend.api.email_settings.send_mime")
    def test_mailgun_error_maps_to_status(
        self,
        _name: str,
        exc_name: str,
        exc_arg: str,
        expected_status: int,
        mock_send_mime: MagicMock,
        _mock_setting: MagicMock,
    ):
        import products.conversations.backend.mailgun as mailgun_mod

        mock_send_mime.side_effect = getattr(mailgun_mod, exc_name)(exc_arg)

        response = self.client.post(
            "/api/conversations/v1/email/send-test", self._post(), content_type="application/json"
        )

        assert response.status_code == expected_status

    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    @patch("products.conversations.backend.api.email_settings.send_mime")
    def test_domain_not_registered_flips_verified(self, mock_send_mime: MagicMock, _mock_setting: MagicMock):
        from products.conversations.backend.mailgun import MailgunDomainNotRegistered

        mock_send_mime.side_effect = MailgunDomainNotRegistered("gone")

        self.client.post("/api/conversations/v1/email/send-test", self._post(), content_type="application/json")

        self.config.refresh_from_db()
        assert self.config.domain_verified is False
