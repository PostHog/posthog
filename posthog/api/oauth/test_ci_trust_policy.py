from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.ci_trust_policy import CITrustPolicy
from posthog.models.instance_setting import set_instance_setting
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.tasks.email import send_ci_trust_policy_changed
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.test.ci_trust_fixtures import FAKE_CI_ISSUER, with_fake_ci_provider


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Production deploys",
        "issuer": FAKE_CI_ISSUER,
        "repository": "acme/web",
        "repository_id": "1234",
        "ref": "refs/heads/main",
        "scopes": ["error_tracking:write", "annotation:write"],
        **overrides,
    }


@with_fake_ci_provider()
class TestCITrustPolicyAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/ci_trust_policies/"

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    def _create_policy(self, team: Team | None = None, **overrides: Any) -> CITrustPolicy:
        fields = {**_payload(), **overrides}
        return CITrustPolicy.objects.for_team((team or self.team).id).create(team=team or self.team, **fields)

    def _use_token(self, kind: str) -> None:
        if kind == "personal_api_key":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(user=self.user, label="ci", secure_value=hash_key_value(token), scopes=["*"])
        else:
            application = OAuthApplication.objects.create(
                name="Test app",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
                organization=self.organization,
                user=self.user,
            )
            token = "pha_ci_trust_policy_test_token"
            OAuthAccessToken.objects.create(
                user=self.user,
                application=application,
                token=token,
                expires=timezone.now() + timedelta(hours=1),
                scope="ci_trust_policy:read ci_trust_policy:write",
            )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, status.HTTP_403_FORBIDDEN),
            ("admin", OrganizationMembership.Level.ADMIN, status.HTTP_201_CREATED),
            ("owner", OrganizationMembership.Level.OWNER, status.HTTP_201_CREATED),
        ]
    )
    def test_only_organization_admins_and_owners_can_create(
        self, _name: str, level: OrganizationMembership.Level, expected_status: int
    ) -> None:
        self._set_level(level)

        response = self.client.post(self.url, _payload(), format="json")

        assert response.status_code == expected_status, response.json()

    def test_members_can_read_but_not_change_or_delete(self) -> None:
        policy = self._create_policy()

        list_response = self.client.get(self.url)
        patch_response = self.client.patch(f"{self.url}{policy.id}/", {"enabled": False}, format="json")
        delete_response = self.client.delete(f"{self.url}{policy.id}/")

        assert list_response.status_code == status.HTTP_200_OK
        assert [row["id"] for row in list_response.json()["results"]] == [str(policy.id)]
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN
        assert delete_response.status_code == status.HTTP_403_FORBIDDEN
        policy.refresh_from_db()
        assert policy.enabled is True

    @parameterized.expand([("personal_api_key",), ("oauth_token",)])
    def test_tokens_can_read_but_never_write_even_for_an_owner(self, kind: str) -> None:
        self._set_level(OrganizationMembership.Level.OWNER)
        policy = self._create_policy()
        self._use_token(kind)

        list_response = self.client.get(self.url)
        create_response = self.client.post(self.url, _payload(ref="refs/heads/other"), format="json")
        patch_response = self.client.patch(f"{self.url}{policy.id}/", {"enabled": False}, format="json")
        delete_response = self.client.delete(f"{self.url}{policy.id}/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        assert create_response.status_code == status.HTTP_403_FORBIDDEN
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN
        assert delete_response.status_code == status.HTTP_403_FORBIDDEN
        assert CITrustPolicy.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("unsupported_issuer", {"issuer": "https://token.actions.example.org"}, "issuer"),
            ("wildcard_repository", {"repository": "acme/*"}, "repository"),
            ("empty_repository_id", {"repository_id": ""}, "repository_id"),
            ("no_ref_or_environment", {"ref": "", "environment": ""}, "ref"),
            ("wildcard_ref", {"ref": "refs/heads/*"}, "ref"),
            ("no_scopes", {"scopes": []}, "scopes"),
            ("unknown_scope", {"scopes": ["not_a_thing:read"]}, "scopes"),
            ("privileged_scope", {"scopes": ["llm_gateway:read"]}, "scopes"),
            ("credential_scope", {"scopes": ["project:write"]}, "scopes"),
            ("member_management_scope", {"scopes": ["organization_member:write"]}, "scopes"),
            ("own_policy_scope", {"scopes": ["ci_trust_policy:read"]}, "scopes"),
            ("owner_account_scope", {"scopes": ["user:read"]}, "scopes"),
            ("approval_scope", {"scopes": ["approvals:write"]}, "scopes"),
            ("credential_storing_scope", {"scopes": ["integration:write"]}, "scopes"),
            ("agent_run_scope", {"scopes": ["task:write"]}, "scopes"),
            ("experiment_cleanup_agent_scope", {"scopes": ["experiment:write"]}, "scopes"),
        ]
    )
    def test_rejects_invalid_policies(self, _name: str, overrides: dict[str, Any], field: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        response = self.client.post(self.url, _payload(**overrides), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == field
        assert not CITrustPolicy.objects.for_team(self.team.id).exists()

    def test_impersonated_sessions_can_read_but_not_change_policies(self) -> None:
        self._set_level(OrganizationMembership.Level.OWNER)
        policy = self._create_policy()

        with patch("posthog.api.oauth.ci_trust_policy.is_impersonated", return_value=True):
            list_response = self.client.get(self.url)
            create_response = self.client.post(self.url, _payload(ref="refs/heads/other"), format="json")
            patch_response = self.client.patch(f"{self.url}{policy.id}/", {"enabled": False}, format="json")
            delete_response = self.client.delete(f"{self.url}{policy.id}/")

        assert list_response.status_code == status.HTTP_200_OK
        assert create_response.status_code == status.HTTP_403_FORBIDDEN
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN
        assert delete_response.status_code == status.HTTP_403_FORBIDDEN
        assert CITrustPolicy.objects.for_team(self.team.id).count() == 1

    def test_rejects_a_second_policy_with_the_same_conditions(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        self._create_policy()

        response = self.client.post(self.url, _payload(name="Duplicate"), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_policies_of_other_projects_are_not_listed(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self._create_policy(team=other_team)

        response = self.client.get(self.url)

        assert response.json()["results"] == []

    @patch("posthog.api.oauth.ci_trust_policy.send_ci_trust_policy_changed")
    def test_every_change_is_logged_and_emailed_to_admins(self, mock_send: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        with self.captureOnCommitCallbacks(execute=True):
            policy_id = self.client.post(self.url, _payload(), format="json").json()["id"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"{self.url}{policy_id}/", {"scopes": ["annotation:write"]}, format="json")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"{self.url}{policy_id}/")

        activities = list(
            ActivityLog.objects.filter(scope="CITrustPolicy", item_id=policy_id)
            .order_by("created_at")
            .values_list("activity", flat=True)
        )
        assert activities == ["created", "updated", "deleted"]
        assert [call.args[3] for call in mock_send.delay.call_args_list] == ["created", "updated", "deleted"]
        assert {call.args[4] for call in mock_send.delay.call_args_list} == {self.user.id}


class TestSendCITrustPolicyChangedEmail(APIBaseTest):
    @patch("posthog.tasks.email.EmailMessage")
    def test_emails_every_active_admin_and_owner(self, MockEmailMessage: MagicMock) -> None:
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        sent = mock_email_messages(MockEmailMessage)
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        admin = User.objects.create_and_join(self.organization, "admin@example.com", None)
        OrganizationMembership.objects.filter(user=admin).update(level=OrganizationMembership.Level.ADMIN)
        User.objects.create_and_join(self.organization, "member@example.com", None)
        inactive_admin = User.objects.create_and_join(self.organization, "inactive@example.com", None)
        OrganizationMembership.objects.filter(user=inactive_admin).update(level=OrganizationMembership.Level.ADMIN)
        inactive_admin.is_active = False
        inactive_admin.save()
        other_org = Organization.objects.create(name="Other")
        User.objects.create_and_join(other_org, "outsider@example.com", None, level=OrganizationMembership.Level.OWNER)

        send_ci_trust_policy_changed(self.team.id, "policy-id", "Production deploys", "created", self.user.id)

        assert len(sent) == 1
        assert sorted(recipient["raw_email"] for recipient in sent[0].to) == sorted(
            [self.user.email, "admin@example.com"]
        )
        assert "Production deploys" in sent[0].html_body
