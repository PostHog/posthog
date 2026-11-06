from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.email import CUSTOMER_IO_TEMPLATE_ID_MAP, WORKFLOWS_TEMPLATE_ID_MAP
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.instance_setting import set_instance_setting
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.models.workload_trust_policy import WorkloadTrustPolicy, WorkloadTrustPolicyRequest
from posthog.tasks.email import send_workload_trust_policy_changed
from posthog.tasks.test.utils_email_tests import mock_email_messages
from posthog.workload_identity.test.fixtures import (
    FAKE_WORKLOAD_ISSUER,
    FAKE_WORKLOAD_PROVIDER,
    with_fake_workload_provider,
)
from posthog.workload_identity.trust_policy import DUPLICATE_POLICY_MESSAGE, normalize_workload_conditions


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Production deploys",
        "issuer": FAKE_WORKLOAD_ISSUER,
        "subject_name": "acme/web",
        "subject": "1234",
        "conditions": {"ref": "refs/heads/main"},
        "scopes": ["error_tracking:write", "annotation:write"],
        **overrides,
    }


def use_token(test: APIBaseTest, kind: str, oauth_scope: str) -> None:
    if kind == "personal_api_key":
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(user=test.user, label="ci", secure_value=hash_key_value(token), scopes=["*"])
    else:
        application = OAuthApplication.objects.create(
            name="Test app",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=test.organization,
            user=test.user,
        )
        token = f"pha_workload_trust_test_{application.pk}"
        OAuthAccessToken.objects.create(
            user=test.user,
            application=application,
            token=token,
            expires=timezone.now() + timedelta(hours=1),
            scope=oauth_scope,
        )
    test.client.logout()
    test.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


@with_fake_workload_provider()
class TestWorkloadTrustPolicyAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/workload_trust_policies/"

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    def _create_policy(self, team: Team | None = None, **overrides: Any) -> WorkloadTrustPolicy:
        fields = {**_payload(), **overrides}
        return WorkloadTrustPolicy.objects.for_team((team or self.team).id).create(team=team or self.team, **fields)

    def _use_token(self, kind: str) -> None:
        use_token(self, kind, "workload_trust_policy:read workload_trust_policy:write")

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

    def test_risky_scopes_are_grantable_and_come_with_a_warning(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        created = self.client.post(self.url, _payload(scopes=["organization_member:write"]), format="json")
        providers = self.client.get(f"{self.url}providers/").json()

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert "organization_member:write" in providers["risky_scopes"]
        assert "task:write" not in providers["grantable_scopes"]
        assert [claim["label"] for claim in providers["supported"][0]["condition_claims"]] == [
            "Branch or tag",
            "Environment",
        ]

    def test_members_can_neither_read_nor_change_policies(self) -> None:
        policy = self._create_policy()

        list_response = self.client.get(self.url)
        retrieve_response = self.client.get(f"{self.url}{policy.id}/")
        providers_response = self.client.get(f"{self.url}providers/")
        patch_response = self.client.patch(f"{self.url}{policy.id}/", {"enabled": False}, format="json")
        delete_response = self.client.delete(f"{self.url}{policy.id}/")

        assert list_response.status_code == status.HTTP_403_FORBIDDEN
        assert retrieve_response.status_code == status.HTTP_403_FORBIDDEN
        assert providers_response.status_code == status.HTTP_403_FORBIDDEN
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
        create_response = self.client.post(self.url, _payload(conditions={"ref": "refs/heads/other"}), format="json")
        patch_response = self.client.patch(f"{self.url}{policy.id}/", {"enabled": False}, format="json")
        delete_response = self.client.delete(f"{self.url}{policy.id}/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        assert create_response.status_code == status.HTTP_403_FORBIDDEN
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN
        assert delete_response.status_code == status.HTTP_403_FORBIDDEN
        assert WorkloadTrustPolicy.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("unsupported_issuer", {"issuer": "https://token.actions.example.org"}, "issuer"),
            ("wildcard_subject_name", {"subject_name": "acme/*"}, "subject_name"),
            ("empty_subject", {"subject": ""}, "subject"),
            ("no_conditions", {"conditions": {}}, "conditions"),
            ("only_empty_conditions", {"conditions": {"ref": "", "environment": ""}}, "conditions"),
            ("conditions_not_an_object", {"conditions": ["ref"]}, "conditions"),
            ("condition_claim_the_provider_does_not_allow", {"conditions": {"sha": "abc123"}}, "conditions"),
            ("non_string_condition_value", {"conditions": {"ref": 1}}, "conditions"),
            ("null_condition_value", {"conditions": {"ref": None}}, "conditions"),
            ("wildcard_condition_value", {"conditions": {"ref": "refs/heads/*"}}, "conditions"),
            ("padded_condition_value", {"conditions": {"ref": " refs/heads/main"}}, "conditions"),
            ("null_character_in_condition_value", {"conditions": {"ref": "refs/heads/main\x00"}}, "conditions"),
            ("overlong_condition_value", {"conditions": {"ref": "r" * 201}}, "conditions"),
            ("no_scopes", {"scopes": []}, "scopes"),
            ("unknown_scope", {"scopes": ["not_a_thing:read"]}, "scopes"),
            ("privileged_scope", {"scopes": ["llm_gateway:read"]}, "scopes"),
            ("credential_scope", {"scopes": ["project:write"]}, "scopes"),
            ("own_policy_scope", {"scopes": ["workload_trust_policy:read"]}, "scopes"),
            ("agent_run_scope", {"scopes": ["task:write"]}, "scopes"),
            ("training_run_scope", {"scopes": ["autoresearch:write"]}, "scopes"),
            ("workflow_task_scope", {"scopes": ["hog_flow:write"]}, "scopes"),
            ("owner_account_scope", {"scopes": ["user:write"]}, "scopes"),
            ("app_token_scope", {"scopes": ["streamlit_app:read"]}, "scopes"),
            ("webhook_feed_scope", {"scopes": ["webhook:write"]}, "scopes"),
            ("batch_export_feed_scope", {"scopes": ["batch_export:write"]}, "scopes"),
            ("subscription_feed_scope", {"scopes": ["subscription:write"]}, "scopes"),
            ("sharing_link_scope", {"scopes": ["sharing_configuration:write"]}, "scopes"),
            ("sharing_link_read_scope", {"scopes": ["sharing_configuration:read"]}, "scopes"),
            ("owner_ai_chat_scope", {"scopes": ["conversation:read"]}, "scopes"),
            ("owner_task_scope", {"scopes": ["task:read"]}, "scopes"),
        ]
    )
    def test_rejects_invalid_policies(self, _name: str, overrides: dict[str, Any], field: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        response = self.client.post(self.url, _payload(**overrides), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == field
        assert not WorkloadTrustPolicy.objects.for_team(self.team.id).exists()

    def test_impersonated_sessions_can_read_but_not_change_policies(self) -> None:
        self._set_level(OrganizationMembership.Level.OWNER)
        policy = self._create_policy()

        with patch("posthog.workload_identity.trust_policy.is_impersonated", return_value=True):
            list_response = self.client.get(self.url)
            create_response = self.client.post(
                self.url, _payload(conditions={"ref": "refs/heads/other"}), format="json"
            )
            patch_response = self.client.patch(f"{self.url}{policy.id}/", {"enabled": False}, format="json")
            delete_response = self.client.delete(f"{self.url}{policy.id}/")

        assert list_response.status_code == status.HTTP_200_OK
        assert create_response.status_code == status.HTTP_403_FORBIDDEN
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN
        assert delete_response.status_code == status.HTTP_403_FORBIDDEN
        assert WorkloadTrustPolicy.objects.for_team(self.team.id).count() == 1

    def test_rejects_a_second_policy_whose_conditions_differ_only_by_an_empty_value(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        self._create_policy()

        response = self.client.post(
            self.url,
            _payload(name="Duplicate", conditions={"environment": "", "ref": "refs/heads/main"}),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == DUPLICATE_POLICY_MESSAGE

    @parameterized.expand(
        [
            (
                "key_order",
                {"ref": "refs/heads/main", "environment": "production"},
                {"environment": "production", "ref": "refs/heads/main"},
                False,
            ),
            ("empty_valued_key", {"ref": "refs/heads/main"}, {"ref": "refs/heads/main", "environment": ""}, False),
            ("different_value", {"ref": "refs/heads/main"}, {"ref": "refs/heads/release"}, True),
            (
                "extra_condition",
                {"ref": "refs/heads/main"},
                {"ref": "refs/heads/main", "environment": "production"},
                True,
            ),
        ]
    )
    def test_unique_constraint_compares_conditions_by_content(
        self, _name: str, stored: dict[str, str], second: dict[str, str], allowed: bool
    ) -> None:
        self._create_policy(conditions=stored)
        normalized = normalize_workload_conditions(second, FAKE_WORKLOAD_PROVIDER)

        if allowed:
            self._create_policy(name="Second", conditions=normalized)
        else:
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._create_policy(name="Second", conditions=normalized)

        assert "" not in normalized.values()
        assert WorkloadTrustPolicy.objects.for_team(self.team.id).count() == (2 if allowed else 1)

    def test_policies_of_other_projects_are_not_listed(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self._create_policy(team=other_team)
        self._set_level(OrganizationMembership.Level.ADMIN)

        response = self.client.get(self.url)

        assert response.json()["results"] == []

    @patch("posthog.workload_identity.trust_policy.send_workload_trust_policy_changed")
    def test_every_change_is_logged_and_emailed_to_admins(self, mock_send: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        with self.captureOnCommitCallbacks(execute=True):
            policy_id = self.client.post(self.url, _payload(), format="json").json()["id"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"{self.url}{policy_id}/", {"scopes": ["annotation:write"]}, format="json")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"{self.url}{policy_id}/")

        activities = list(
            ActivityLog.objects.filter(scope="WorkloadTrustPolicy", item_id=policy_id)
            .order_by("created_at")
            .values_list("activity", flat=True)
        )
        assert activities == ["created", "updated", "deleted"]
        assert [call.args[3] for call in mock_send.delay.call_args_list] == ["created", "updated", "deleted"]
        assert {call.args[4] for call in mock_send.delay.call_args_list} == {self.user.id}


class TestSendWorkloadTrustPolicyChangedEmail(APIBaseTest):
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

        send_workload_trust_policy_changed(self.team.id, "policy-id", "Production deploys", "created", self.user.id)

        assert len(sent) == 1
        assert sorted(recipient["raw_email"] for recipient in sent[0].to) == sorted(
            [self.user.email, "admin@example.com"]
        )
        assert "Production deploys" in sent[0].html_body
        assert sent[0].use_http is True
        assert sent[0].template_name in CUSTOMER_IO_TEMPLATE_ID_MAP
        assert sent[0].template_name in WORKFLOWS_TEMPLATE_ID_MAP


@with_fake_workload_provider()
class TestWorkloadTrustPolicyRequestAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.url = f"/api/projects/{self.team.id}/workload_trust_policy_requests/"

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    def _create_request(self, **overrides: Any) -> WorkloadTrustPolicyRequest:
        return WorkloadTrustPolicyRequest.objects.for_team(self.team.id).create(
            team=self.team, requested_by=self.user, **{**_payload(), **overrides}
        )

    @parameterized.expand(
        [
            ("unverified_app", False, False, False),
            ("verified_app", True, False, True),
            ("first_party_app", False, True, True),
        ]
    )
    def test_member_asks_for_a_policy_with_an_oauth_token(
        self, _name: str, is_verified: bool, is_first_party: bool, expected_verified: bool
    ) -> None:
        owner = User.objects.create_and_join(
            self.organization, "owner@example.com", None, first_name="Olive", level=OrganizationMembership.Level.OWNER
        )
        owner.last_name = "Owner"
        owner.save()
        use_token(self, "oauth_token", "workload_trust_policy_request:write")
        OAuthApplication.objects.filter(name="Test app").update(is_verified=is_verified, is_first_party=is_first_party)

        response = self.client.post(self.url, _payload(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["status"] == "pending"
        assert body["can_approve"] is False
        assert body["approvers"] == ["Olive Owner"]
        assert body["requested_via"] == "Test app"
        assert body["requested_via_verified"] is expected_verified
        assert body["approval_url"].endswith(f"/project/{self.team.id}/workload-trust-policy-requests/{body['id']}")
        assert not WorkloadTrustPolicy.objects.for_team(self.team.id).exists()

        OAuthApplication.objects.filter(name="Test app").update(
            name="Renamed app", is_verified=False, is_first_party=False
        )
        shown = self.client.get(f"{self.url}{body['id']}/").json()

        assert (shown["requested_via"], shown["requested_via_verified"]) == ("Renamed app", False)

    @parameterized.expand([("visible", None, ["Olive Owner"]), ("hidden_member_list", set(), [])])
    def test_member_sees_only_the_approvers_the_members_list_shows_them(
        self, _name: str, visible_membership_ids: set[str] | None, expected_approvers: list[str]
    ) -> None:
        owner = User.objects.create_and_join(
            self.organization, "owner@example.com", None, first_name="Olive", level=OrganizationMembership.Level.OWNER
        )
        owner.last_name = "Owner"
        owner.save()
        policy_request = self._create_request()

        with patch(
            "posthog.workload_identity.trust_policy.restricted_visible_membership_ids",
            return_value=visible_membership_ids,
        ):
            body = self.client.get(f"{self.url}{policy_request.id}/").json()

        assert body["approvers"] == expected_approvers

    def test_admin_sees_they_can_approve_and_the_risky_scopes(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        policy_request = self._create_request(scopes=["organization_member:write", "annotation:write"])

        body = self.client.get(f"{self.url}{policy_request.id}/").json()

        assert body["can_approve"] is True
        assert body["approvers"] == []
        assert list(body["risky_scopes"]) == ["organization_member:write"]

    def test_a_token_minted_while_impersonating_cannot_ask_for_a_policy(self) -> None:
        staff = User.objects.create_user(email="staff@example.com", password=None, first_name="Staff", is_staff=True)
        use_token(self, "oauth_token", "workload_trust_policy_request:write")
        OAuthAccessToken.objects.filter(user=self.user).update(impersonated_by=staff)

        response = self.client.post(self.url, _payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not WorkloadTrustPolicyRequest.objects.for_team(self.team.id).exists()

    def test_creating_a_request_needs_the_request_scope(self) -> None:
        use_token(self, "oauth_token", "workload_trust_policy:read")

        response = self.client.post(self.url, _payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_requests_cannot_be_edited(self) -> None:
        policy_request = self._create_request()

        response = self.client.patch(f"{self.url}{policy_request.id}/", {"scopes": ["insight:write"]}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @parameterized.expand(
        [
            ("member_session", OrganizationMembership.Level.MEMBER, None),
            ("owner_personal_api_key", OrganizationMembership.Level.OWNER, "personal_api_key"),
            ("owner_oauth_token", OrganizationMembership.Level.OWNER, "oauth_token"),
        ]
    )
    def test_only_an_admin_browser_session_can_approve(
        self, _name: str, level: OrganizationMembership.Level, token_kind: str | None
    ) -> None:
        self._set_level(level)
        policy_request = self._create_request()
        if token_kind:
            use_token(self, token_kind, "workload_trust_policy_request:write")

        response = self.client.post(f"{self.url}{policy_request.id}/approve/")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        policy_request.refresh_from_db()
        assert policy_request.status == WorkloadTrustPolicyRequest.Status.PENDING
        assert not WorkloadTrustPolicy.objects.for_team(self.team.id).exists()

    @parameterized.expand([("approve",), ("reject",)])
    def test_impersonated_sessions_cannot_resolve_requests(self, resolution: str) -> None:
        self._set_level(OrganizationMembership.Level.OWNER)
        policy_request = self._create_request()

        with patch("posthog.workload_identity.trust_policy.is_impersonated", return_value=True):
            read_response = self.client.get(f"{self.url}{policy_request.id}/")
            response = self.client.post(f"{self.url}{policy_request.id}/{resolution}/")

        assert read_response.status_code == status.HTTP_200_OK
        assert response.status_code == status.HTTP_403_FORBIDDEN
        policy_request.refresh_from_db()
        assert policy_request.status == WorkloadTrustPolicyRequest.Status.PENDING

    @patch("posthog.workload_identity.trust_policy.send_workload_trust_policy_changed")
    def test_admin_approves_their_own_request_which_creates_the_policy(self, mock_send: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        created = self.client.post(
            self.url, _payload(conditions={"environment": "", "ref": "refs/heads/main"}), format="json"
        )
        policy_request = WorkloadTrustPolicyRequest.objects.for_team(self.team.id).get(pk=created.json()["id"])

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"{self.url}{policy_request.id}/approve/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        policy = WorkloadTrustPolicy.objects.for_team(self.team.id).get()
        assert response.json()["status"] == "approved"
        assert response.json()["policy_id"] == str(policy.id)
        assert policy_request.conditions == {"ref": "refs/heads/main"}
        assert (policy.subject, policy.conditions, sorted(policy.scopes), policy.created_by_id) == (
            "1234",
            {"ref": "refs/heads/main"},
            ["annotation:write", "error_tracking:write"],
            self.user.id,
        )
        assert [call.args[3] for call in mock_send.delay.call_args_list] == ["created"]
        assert list(
            ActivityLog.objects.filter(scope="WorkloadTrustPolicyRequest", item_id=str(policy_request.id))
            .order_by("created_at")
            .values_list("activity", flat=True)
        ) == ["created", "approved"]

    def test_admin_rejects_a_request(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        policy_request = self._create_request()

        response = self.client.post(f"{self.url}{policy_request.id}/reject/")

        assert response.json()["status"] == "rejected"
        assert not WorkloadTrustPolicy.objects.for_team(self.team.id).exists()

    @parameterized.expand([("expired",), ("already_rejected",)])
    def test_a_request_that_is_not_pending_cannot_be_approved(self, case: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        if case == "expired":
            policy_request = self._create_request(expires_at=datetime(2020, 1, 1, tzinfo=UTC))
        else:
            policy_request = self._create_request()
            self.client.post(f"{self.url}{policy_request.id}/reject/")

        response = self.client.post(f"{self.url}{policy_request.id}/approve/")
        status_shown = self.client.get(f"{self.url}{policy_request.id}/").json()["status"]

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert status_shown == ("expired" if case == "expired" else "rejected")
        assert not WorkloadTrustPolicy.objects.for_team(self.team.id).exists()

    def test_requests_are_rate_limited_per_user_and_project(self) -> None:
        for _ in range(10):
            assert self.client.post(self.url, _payload(), format="json").status_code == status.HTTP_201_CREATED

        throttled = self.client.post(self.url, _payload(), format="json")
        other_member = User.objects.create_and_join(self.organization, "other@example.com", None)
        self.client.force_login(other_member)
        other_member_response = self.client.post(self.url, _payload(), format="json")

        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert other_member_response.status_code == status.HTTP_201_CREATED
