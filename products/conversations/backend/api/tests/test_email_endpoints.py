from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.conversations.backend.models import TeamConversationsEmailConfig


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
        config = TeamConversationsEmailConfig.objects.get(team=self.team)
        assert config.from_email == "support@example.com"
        assert config.domain == "example.com"

    @patch("products.conversations.backend.api.email_settings.mailgun_add_domain", return_value={})
    @patch(
        "products.conversations.backend.api.email_settings.get_instance_setting",
        return_value="mg.posthog.com",
    )
    def test_connect_rejects_duplicate_domain_different_casing(
        self, _mock_setting: MagicMock, _mock_mailgun: MagicMock
    ):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )

        # Second team tries the same domain with different casing
        second_team = Team.objects.create(organization=self.organization)
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
            ("disconnect", "post", "/api/conversations/v1/email/disconnect", {}),
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

        response = self.client.post(
            "/api/conversations/v1/email/disconnect",
            content_type="application/json",
        )
        assert response.status_code == 200


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
