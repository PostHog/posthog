from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.conversations.backend.models import EmailChannel
from products.conversations.backend.models.ticket import Ticket


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
    def test_cross_team_domain_rejected(self, _mock_setting: MagicMock, _mock_mailgun: MagicMock):
        self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "support@example.com", "from_name": "Support"},
            content_type="application/json",
        )

        second_team = Team.objects.create(organization=self.organization)
        self.user.current_team = second_team
        self.user.save()

        r2 = self.client.post(
            "/api/conversations/v1/email/connect",
            {"from_email": "billing@example.com", "from_name": "Billing"},
            content_type="application/json",
        )
        assert r2.status_code == 409
        assert "already in use" in r2.json()["error"]

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
        config2_id = r2.json()["config"]["id"]

        response = self.client.post(
            "/api/conversations/v1/email/verify-domain",
            {"config_id": config2_id},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["domain_verified"] is True

        # Both configs should be verified
        configs = EmailChannel.objects.filter(team=self.team)
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

    @patch("products.conversations.backend.tasks.get_smtp_connection")
    @patch("products.conversations.backend.tasks.get_instance_setting", return_value="mg.posthog.com")
    def test_send_email_reply_uses_ticket_config(self, _mock_setting: MagicMock, mock_smtp: MagicMock):
        from products.conversations.backend.tasks import send_email_reply

        config1 = self._create_config("support@example.com", "aaa111")
        self._create_config("billing@example.com", "bbb222")
        ticket = self._create_ticket(config1)

        mock_conn = MagicMock()
        mock_smtp.return_value = mock_conn

        from posthog.models.comment import Comment

        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Reply from agent",
        )

        send_email_reply(
            ticket_id=str(ticket.id),
            team_id=self.team.id,
            comment_id=str(comment.id),
            content="Reply from agent",
            rich_content=None,
            author_name="Agent",
        )

        mock_conn.send_messages.assert_called_once()
        sent_msg = mock_conn.send_messages.call_args[0][0][0]
        assert "support@example.com" in sent_msg.from_email

    def test_send_email_reply_skips_when_no_config(self):
        from products.conversations.backend.tasks import send_email_reply

        ticket = self._create_ticket(None)

        from posthog.models.comment import Comment

        comment = Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Reply",
        )

        # Should return without error (logs warning, doesn't crash)
        send_email_reply(
            ticket_id=str(ticket.id),
            team_id=self.team.id,
            comment_id=str(comment.id),
            content="Reply",
            rich_content=None,
            author_name="Agent",
        )
