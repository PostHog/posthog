from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.user import UserType
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.service_accounts.emails import generated_service_account_email

from products.access_control.backend.models.role import Role, RoleMembership


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
        role = Role.objects.create(organization=self.organization, name="Default role")
        self.organization.default_role_id = role.id
        self.organization.save(update_fields=["default_role_id"])
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
        assert not RoleMembership.objects.filter(user=account).exists()
        assert not FileSystemShortcut.objects.filter(user=account).exists()
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
