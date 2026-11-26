from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthGrant, OAuthRefreshToken
from posthog.models.user import UserType
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.service_accounts.emails import generated_service_account_email

from products.access_control.backend.models.role import Role, RoleMembership
from products.annotations.backend.facade.testing import create_annotation


class TestServiceAccountAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.memberships.filter(user=self.user).update(level=OrganizationMembership.Level.ADMIN)
        self.url = f"/api/organizations/{self.organization.id}/service_accounts/"
        self.account = User.objects.create_and_join(
            self.organization, "service@example.com", None, first_name="Deploy", type=UserType.SERVICE_ACCOUNT
        )
        self.flag = self.enterContext(
            patch("posthog.api.service_account.posthoganalytics.feature_enabled", return_value=True)
        )

    def test_create_generates_identity_and_member_access(self) -> None:
        response = self.client.post(self.url, {"name": "Deploy bot"})
        assert response.status_code == 201, response.json()
        account = User.objects.get(uuid=response.json()["id"])
        assert account.type == UserType.SERVICE_ACCOUNT
        assert account.email == generated_service_account_email(account.uuid)
        assert account.first_name == "Deploy bot"
        assert not account.has_usable_password()
        assert not account.is_staff
        assert not account.allow_impersonation
        assert account.is_active
        assert account.current_organization_id == self.organization.id
        assert list(account.organization_memberships.values_list("organization_id", "level")) == [
            (self.organization.id, OrganizationMembership.Level.MEMBER)
        ]
        second = self.client.post(self.url, {"name": "Deploy bot"})
        assert second.status_code == 201
        assert second.json()["user"]["email"] != account.email

    @parameterized.expand([False, None])
    def test_creation_flag_fails_closed(self, enabled) -> None:
        self.flag.return_value = enabled
        count = User.objects.count()
        response = self.client.post(self.url, {"name": "Deploy bot"})
        assert response.status_code == 403
        assert User.objects.count() == count
        assert self.client.get(self.url).status_code == 200
        assert self.client.patch(f"{self.url}{self.account.uuid}/", {"name": "Renamed"}).status_code == 200

    @parameterized.expand([OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.OWNER])
    def test_admins_and_owners_can_manage_accounts(self, level) -> None:
        self.organization.memberships.filter(user=self.user).update(level=level)
        assert self.client.get(self.url).status_code == 200
        assert self.client.get(f"{self.url}{self.account.uuid}/").status_code == 200
        assert self.client.patch(f"{self.url}{self.account.uuid}/", {"name": "Renamed"}).status_code == 200
        assert self.client.post(self.url, {"name": "New bot"}).status_code == 201

    @parameterized.expand(["get", "post", "retrieve", "patch"])
    def test_members_cannot_manage_accounts(self, method) -> None:
        self.organization.memberships.filter(user=self.user).update(level=OrganizationMembership.Level.MEMBER)
        url = self.url if method in ("get", "post") else f"{self.url}{self.account.uuid}/"
        response = getattr(self.client, "get" if method == "retrieve" else method)(url, {"name": "Changed"})
        assert response.status_code == 403
        self.account.refresh_from_db()
        assert self.account.first_name == "Deploy"

    def test_list_is_scoped_to_organization_and_account_type(self) -> None:
        other_org = Organization.objects.create(name="Other organization")
        User.objects.create_and_join(other_org, "other@example.com", None, type=UserType.SERVICE_ACCOUNT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert [account["id"] for account in response.json()["results"]] == [str(self.account.uuid)]
        assert response.json()["results"][0]["user"]["type"] == UserType.SERVICE_ACCOUNT

    @parameterized.expand([("human", "get"), ("human", "patch"), ("other_org", "get"), ("other_org", "patch")])
    def test_rejects_targets_outside_service_accounts_in_this_organization(self, target, method) -> None:
        if target == "human":
            user = self.user
        else:
            other_org = Organization.objects.create(name="Other organization")
            user = User.objects.create_and_join(other_org, "other@example.com", None, type=UserType.SERVICE_ACCOUNT)
        response = getattr(self.client, method)(f"{self.url}{user.uuid}/", {"name": "Changed"})
        assert response.status_code == 404
        user.refresh_from_db()
        assert user.first_name != "Changed"

    @parameterized.expand(
        [
            ("email", "changed@example.com"),
            ("type", "human"),
            ("level", OrganizationMembership.Level.OWNER),
            ("is_active", False),
            ("is_staff", True),
            ("password", "not-a-real-password"),
            ("organization_id", "00000000-0000-0000-0000-000000000000"),
        ]
    )
    def test_rejects_identity_and_permission_fields(self, field, value) -> None:
        payload = {"name": "Changed", field: value}
        assert self.client.post(self.url, payload).status_code == 400
        assert self.client.patch(f"{self.url}{self.account.uuid}/", payload).status_code == 400
        self.account.refresh_from_db()
        assert self.account.first_name == "Deploy"

    def test_rename_preserves_identity_and_membership(self) -> None:
        original_email = self.account.email
        original_membership = self.account.organization_memberships.get()
        response = self.client.patch(f"{self.url}{self.account.uuid}/", {"name": "Renamed"})
        assert response.status_code == 200, response.json()
        self.account.refresh_from_db()
        assert self.account.first_name == "Renamed"
        assert self.account.email == original_email
        assert self.account.organization_memberships.get().id == original_membership.id
        assert response.json()["id"] == str(self.account.uuid)

    @parameterized.expand(["", " " * 3, "x" * 151])
    def test_rejects_invalid_names(self, name) -> None:
        assert self.client.post(self.url, {"name": name}).status_code == 400
        assert self.client.patch(f"{self.url}{self.account.uuid}/", {"name": name}).status_code == 400

    @parameterized.expand(
        [
            ("get", "organization_member:read", 200),
            ("patch", "organization_member:read", 403),
            ("patch", "organization_member:write", 200),
            ("post", "organization_member:write", 201),
            ("get", "insight:read", 403),
        ]
    )
    def test_personal_api_key_scopes(self, method, scope, expected_status) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="Management", secure_value=hash_key_value(token), scopes=[scope]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        url = f"{self.url}{self.account.uuid}/" if method == "patch" else self.url
        response = getattr(self.client, method)(url, {"name": "Renamed"})
        assert response.status_code == expected_status, response.json()

    def test_token_cannot_manage_an_organization_outside_its_scope(self) -> None:
        other_org = Organization.objects.create(name="Other organization")
        self.user.join(organization=other_org, level=OrganizationMembership.Level.OWNER)
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Other organization",
            secure_value=hash_key_value(token),
            scopes=["organization_member:read", "organization_member:write"],
            scoped_organizations=[str(other_org.id)],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert self.client.get(self.url).status_code == 403
        assert self.client.post(self.url, {"name": "Forbidden"}).status_code == 403

    @parameterized.expand(["valid", "expired", "revoked"])
    def test_disable_and_enable_preserve_only_valid_credentials(self, credential_state) -> None:
        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            user=self.account, label="Deploy", secure_value=hash_key_value(token), scopes=["user:read"]
        )
        membership = self.account.organization_memberships.get()
        role = Role.objects.create(organization=self.organization, name="Deployers")
        assignment = RoleMembership.objects.create(role=role, user=self.account, organization_member=membership)
        account_client = APIClient()
        account_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert account_client.get("/api/users/@me/").status_code == 200

        response = self.client.post(f"{self.url}{self.account.uuid}/disable/", {})
        assert response.status_code == 200, response.json()
        assert response.json()["is_active"] is False
        assert account_client.get("/api/users/@me/").status_code == 401
        assert PersonalAPIKey.objects.get(pk=key.pk).secure_value == key.secure_value
        assert self.account.organization_memberships.get().id == membership.id
        assert RoleMembership.objects.filter(pk=assignment.pk).exists()
        assert self.client.get(f"{self.url}{self.account.uuid}/").status_code == 200
        assert str(self.account.uuid) in [account["id"] for account in self.client.get(self.url).json()["results"]]
        assert (
            self.client.patch(f"{self.url}{self.account.uuid}/", {"name": "Renamed while disabled"}).status_code == 200
        )

        if credential_state == "expired":
            key.expires_at = timezone.now() - timedelta(seconds=1)
            key.save(update_fields=["expires_at"])
        elif credential_state == "revoked":
            key.delete()
        self.flag.return_value = False
        response = self.client.post(f"{self.url}{self.account.uuid}/enable/", {})
        assert response.status_code == 200, response.json()
        assert response.json()["is_active"] is True
        assert account_client.get("/api/users/@me/").status_code == (200 if credential_state == "valid" else 401)
        assert self.account.organization_memberships.get().id == membership.id
        assert RoleMembership.objects.filter(pk=assignment.pk).exists()

    @parameterized.expand(["disable", "enable"])
    def test_lifecycle_actions_reject_members_and_out_of_scope_targets(self, action) -> None:
        other_org = Organization.objects.create(name="Other organization")
        other = User.objects.create_and_join(other_org, "other@example.com", None, type=UserType.SERVICE_ACCOUNT)
        for target in [self.user, other]:
            assert self.client.post(f"{self.url}{target.uuid}/{action}/", {}).status_code == 404
        self.organization.memberships.filter(user=self.user).update(level=OrganizationMembership.Level.MEMBER)
        assert self.client.post(f"{self.url}{self.account.uuid}/{action}/", {}).status_code == 403

    @parameterized.expand(["disable", "enable"])
    def test_lifecycle_actions_require_write_scope(self, action) -> None:
        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            user=self.user, label="Management", secure_value=hash_key_value(token), scopes=["organization_member:read"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert self.client.post(f"{self.url}{self.account.uuid}/{action}/", {}).status_code == 403
        key.scopes = ["organization_member:write"]
        key.save(update_fields=["scopes"])
        assert self.client.post(f"{self.url}{self.account.uuid}/{action}/", {}).status_code == 200

    @parameterized.expand([True, False])
    def test_delete_and_restore_preserve_history_but_not_credentials(self, initially_active) -> None:
        self.account.is_active = initially_active
        self.account.save(update_fields=["is_active"])
        membership = self.account.organization_memberships.get()
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.account, label="Deploy", secure_value=hash_key_value(token), scopes=["user:read"]
        )
        annotation = create_annotation(
            team_id=self.team.pk,
            organization_id=self.organization.pk,
            content="Deployment",
            created_by_id=self.account.pk,
        )
        url = f"{self.url}{self.account.uuid}/"
        assert self.client.delete(url).status_code == 204
        self.account.refresh_from_db()
        assert not self.account.is_active
        assert self.account.organization_memberships.get().pk == membership.pk
        assert not PersonalAPIKey.objects.filter(user=self.account).exists()
        deleted_at = self.client.get(url).json()["deleted_at"]
        assert deleted_at
        assert self.client.delete(url).status_code == 204
        assert self.client.get(url).json()["deleted_at"] == deleted_at
        assert self.client.get(self.url).json()["results"] == []
        assert [item["id"] for item in self.client.get(self.url, {"include_deleted": True}).json()["results"]] == [
            str(self.account.uuid)
        ]
        assert self.client.patch(url, {"name": "Changed"}).status_code == 404
        for action in ["enable", "disable"]:
            assert self.client.post(f"{url}{action}/", {}).status_code == 404
        history_url = f"/api/projects/{self.team.pk}/annotations/{annotation}/"
        assert self.client.get(history_url).json()["created_by"]["uuid"] == str(self.account.uuid)

        self.flag.return_value = False
        response = self.client.post(f"{url}restore/", {})
        assert response.status_code == 200, response.json()
        assert response.json()["deleted_at"] is None
        assert response.json()["is_active"] is True
        assert response.json()["user"]["email"] == self.account.email
        assert self.account.organization_memberships.get().pk == membership.pk
        assert self.client.get(history_url).json()["created_by"]["uuid"] == str(self.account.uuid)
        account_client = APIClient()
        account_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert account_client.get("/api/users/@me/").status_code == 401
        new_token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.account, label="Replacement", secure_value=hash_key_value(new_token), scopes=["user:read"]
        )
        account_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_token}")
        assert account_client.get("/api/users/@me/").status_code == 200

    def test_restore_does_not_enable_an_account_that_was_only_disabled(self) -> None:
        self.account.is_active = False
        self.account.save(update_fields=["is_active"])
        response = self.client.post(f"{self.url}{self.account.uuid}/restore/", {})
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_delete_revokes_oauth_tokens_and_unredeemed_grants(self) -> None:
        application = OAuthApplication.objects.create(
            name="Example integration",
            client_type="public",
            authorization_grant_type="authorization-code",
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )
        access = OAuthAccessToken.objects.create(
            user=self.account,
            application=application,
            token="test-deleted-access",
            expires=timezone.now() + timedelta(hours=1),
            scope="user:read",
        )
        refresh = OAuthRefreshToken.objects.create(
            user=self.account, application=application, token="test-deleted-refresh", access_token=access
        )
        OAuthGrant.objects.create(
            user=self.account,
            application=application,
            code="test-unredeemed-code",
            code_challenge="test-challenge",
            code_challenge_method="S256",
            expires=timezone.now() + timedelta(minutes=5),
            redirect_uri="https://example.com/callback",
            scope="user:read",
        )
        url = f"{self.url}{self.account.uuid}/"
        assert self.client.delete(url).status_code == 204
        assert not OAuthAccessToken.objects.filter(user=self.account).exists()
        assert not OAuthRefreshToken.objects.filter(user=self.account).exists()
        assert not OAuthGrant.objects.filter(user=self.account).exists()
        assert self.client.post(f"{url}restore/", {}).status_code == 200
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access.token}")
        assert client.get("/api/users/@me/").status_code == 401
        response = APIClient().post(
            "/oauth/token/",
            {"grant_type": "refresh_token", "refresh_token": refresh.token, "client_id": application.client_id},
        )
        assert response.status_code == 400, response.content
        assert response.json()["error"] == "invalid_grant"

    @parameterized.expand(["delete", "restore"])
    def test_deletion_actions_reject_members_and_out_of_scope_targets(self, action) -> None:
        other_org = Organization.objects.create(name="Other organization")
        other = User.objects.create_and_join(other_org, "other@example.com", None, type=UserType.SERVICE_ACCOUNT)

        def perform(target):
            url = f"{self.url}{target.uuid}/"
            return self.client.delete(url) if action == "delete" else self.client.post(f"{url}restore/", {})

        for target in [self.user, other]:
            assert perform(target).status_code == 404
        self.organization.memberships.filter(user=self.user).update(level=OrganizationMembership.Level.MEMBER)
        assert perform(self.account).status_code == 403

    @parameterized.expand(["delete", "restore"])
    def test_deletion_actions_require_write_scope(self, action) -> None:
        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            user=self.user, label="Management", secure_value=hash_key_value(token), scopes=["organization_member:read"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        url = f"{self.url}{self.account.uuid}/"

        def perform():
            return self.client.delete(url) if action == "delete" else self.client.post(f"{url}restore/", {})

        assert perform().status_code == 403
        key.scopes = ["organization_member:write"]
        key.save(update_fields=["scopes"])
        assert perform().status_code == (204 if action == "delete" else 200)

    def test_credential_revocation_failure_rolls_back_deletion(self) -> None:
        PersonalAPIKey.objects.create(
            user=self.account, label="Deploy", secure_value=hash_key_value(generate_random_token_personal())
        )
        with patch(
            "posthog.models.personal_api_key.PersonalAPIKey.delete", side_effect=RuntimeError("revocation failed")
        ):
            assert self.client.delete(f"{self.url}{self.account.uuid}/").status_code == 500
        self.account.refresh_from_db()
        assert self.account.is_active
        assert self.client.get(f"{self.url}{self.account.uuid}/").json()["deleted_at"] is None
        assert PersonalAPIKey.objects.filter(user=self.account).exists()
