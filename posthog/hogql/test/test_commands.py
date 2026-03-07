from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.commands import execute_command
from posthog.hogql.errors import QueryError

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.personal_api_key_service import create_personal_api_key


class TestApiKeyCommandExecutor(BaseTest):
    def test_create_api_key(self):
        node = ast.CreateApiKeyCommand(label="test-key", scopes=["query:read"])
        response = execute_command(node, self.user)

        assert response.columns == ["api_key", "label", "scopes", "created_at"]
        assert len(response.results) == 1
        row = response.results[0]
        assert row[0].startswith("phx_")
        assert row[1] == "test-key"
        assert row[2] == ["query:read"]

        key = PersonalAPIKey.objects.get(user=self.user, label="test-key")
        assert key is not None

    def test_create_api_key_invalid_scope(self):
        node = ast.CreateApiKeyCommand(label="bad-key", scopes=["invalid:scope"])
        with self.assertRaises(QueryError):
            execute_command(node, self.user)

    def test_show_api_keys(self):
        create_personal_api_key(self.user, "key-1", ["query:read"])
        create_personal_api_key(self.user, "key-2", ["insight:write"])

        node = ast.ShowApiKeysCommand()
        response = execute_command(node, self.user)

        assert response.columns == [
            "id",
            "label",
            "mask_value",
            "scopes",
            "created_at",
            "last_used_at",
            "last_rolled_at",
        ]
        assert len(response.results) == 2
        labels = {row[1] for row in response.results}
        assert labels == {"key-1", "key-2"}

    def test_show_api_keys_empty(self):
        node = ast.ShowApiKeysCommand()
        response = execute_command(node, self.user)
        assert response.results == []

    def test_alter_api_key_roll(self):
        key, original_value = create_personal_api_key(self.user, "roll-me", ["query:read"])

        node = ast.AlterApiKeyRollCommand(label="roll-me")
        response = execute_command(node, self.user)

        assert response.columns == ["api_key", "label", "last_rolled_at"]
        assert len(response.results) == 1
        new_value = response.results[0][0]
        assert new_value.startswith("phx_")
        assert new_value != original_value

    def test_alter_api_key_roll_not_found(self):
        node = ast.AlterApiKeyRollCommand(label="nonexistent")
        with self.assertRaises(QueryError):
            execute_command(node, self.user)

    def test_create_api_key_limit(self):
        for i in range(10):
            create_personal_api_key(self.user, f"key-{i}", ["query:read"])

        node = ast.CreateApiKeyCommand(label="too-many", scopes=["query:read"])
        with self.assertRaises(QueryError):
            execute_command(node, self.user)


class TestAccessControlCommandExecutor(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        from ee.models.rbac.role import Role

        self.role = Role.objects.create(
            name="Analysts",
            organization=self.organization,
            created_by=self.user,
        )

    def test_grant_to_role(self):
        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            target_type="role",
            target_name="Analysts",
        )
        response = execute_command(node, self.user, team=self.team)

        assert response.columns == [
            "resource",
            "resource_name",
            "access_level",
            "target_type",
            "target_name",
            "status",
        ]
        assert len(response.results) == 1
        row = response.results[0]
        assert row[0] == "insight"
        assert row[2] == "editor"
        assert row[3] == "role"
        assert row[4] == "Analysts"
        assert row[5] == "granted"

    def test_grant_to_user(self):
        node = ast.GrantCommand(
            access_level="viewer",
            resource="dashboard",
            target_type="user",
            target_name=self.user.email,
        )
        response = execute_command(node, self.user, team=self.team)

        assert response.results[0][5] == "granted"

    def test_grant_to_default(self):
        node = ast.GrantCommand(
            access_level="viewer",
            resource="insight",
            target_type="default",
        )
        response = execute_command(node, self.user, team=self.team)

        assert response.results[0][3] == "default"
        assert response.results[0][5] == "granted"

    def test_grant_with_resource_name(self):
        from posthog.models import Insight

        insight = Insight.objects.create(team=self.team, name="My Conversion Funnel")

        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            resource_name="My Conversion Funnel",
            target_type="role",
            target_name="Analysts",
        )
        response = execute_command(node, self.user, team=self.team)

        assert response.results[0][1] == "My Conversion Funnel"
        assert response.results[0][5] == "granted"

        from ee.models.rbac.access_control import AccessControl

        ac = AccessControl.objects.get(team=self.team, resource="insight")
        assert ac.resource_id == str(insight.id)

    def test_grant_with_feature_flag_key(self):
        from posthog.models.feature_flag import FeatureFlag

        FeatureFlag.objects.create(team=self.team, key="my-flag", created_by=self.user)

        node = ast.GrantCommand(
            access_level="editor",
            resource="feature_flag",
            resource_name="my-flag",
            target_type="default",
        )
        response = execute_command(node, self.user, team=self.team)
        assert response.results[0][5] == "granted"

    def test_grant_resource_name_not_found(self):
        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            resource_name="Nonexistent Insight",
            target_type="default",
        )
        with self.assertRaises(QueryError, msg="insight 'Nonexistent Insight' not found"):
            execute_command(node, self.user, team=self.team)

    def test_grant_resource_name_ambiguous(self):
        from posthog.models import Insight

        Insight.objects.create(team=self.team, name="Duplicate Name")
        Insight.objects.create(team=self.team, name="Duplicate Name")

        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            resource_name="Duplicate Name",
            target_type="default",
        )
        with self.assertRaises(QueryError, msg="Ambiguous"):
            execute_command(node, self.user, team=self.team)

    def test_grant_invalid_resource(self):
        node = ast.GrantCommand(
            access_level="editor",
            resource="nonexistent",
            target_type="default",
        )
        with self.assertRaises(QueryError):
            execute_command(node, self.user, team=self.team)

    def test_grant_invalid_role(self):
        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            target_type="role",
            target_name="Nonexistent Role",
        )
        with self.assertRaises(QueryError):
            execute_command(node, self.user, team=self.team)

    def test_grant_permission_denied(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            target_type="default",
        )
        with self.assertRaises(QueryError):
            execute_command(node, self.user, team=self.team)

    def test_revoke_from_role(self):
        grant_node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            target_type="role",
            target_name="Analysts",
        )
        execute_command(grant_node, self.user, team=self.team)

        revoke_node = ast.RevokeCommand(
            resource="insight",
            target_type="role",
            target_name="Analysts",
        )
        response = execute_command(revoke_node, self.user, team=self.team)

        assert response.results[0][4] == "revoked"

    def test_revoke_not_found(self):
        node = ast.RevokeCommand(
            resource="insight",
            target_type="role",
            target_name="Analysts",
        )
        response = execute_command(node, self.user, team=self.team)
        assert response.results[0][4] == "not_found"

    def test_revoke_by_resource_name(self):
        from posthog.models import Dashboard

        Dashboard.objects.create(team=self.team, name="Marketing Overview")

        execute_command(
            ast.GrantCommand(
                access_level="viewer",
                resource="dashboard",
                resource_name="Marketing Overview",
                target_type="default",
            ),
            self.user,
            team=self.team,
        )

        response = execute_command(
            ast.RevokeCommand(
                resource="dashboard",
                resource_name="Marketing Overview",
                target_type="default",
            ),
            self.user,
            team=self.team,
        )
        assert response.results[0][4] == "revoked"

    def test_show_grants(self):
        execute_command(
            ast.GrantCommand(access_level="editor", resource="insight", target_type="role", target_name="Analysts"),
            self.user,
            team=self.team,
        )
        execute_command(
            ast.GrantCommand(access_level="viewer", resource="dashboard", target_type="default"),
            self.user,
            team=self.team,
        )

        node = ast.ShowGrantsCommand()
        response = execute_command(node, self.user, team=self.team)

        assert response.columns == [
            "resource",
            "resource_name",
            "access_level",
            "target_type",
            "target_name",
            "created_at",
        ]
        assert len(response.results) == 2

    def test_show_grants_displays_resource_name(self):
        from posthog.models import Insight

        Insight.objects.create(team=self.team, name="Revenue Dashboard")

        execute_command(
            ast.GrantCommand(
                access_level="editor",
                resource="insight",
                resource_name="Revenue Dashboard",
                target_type="default",
            ),
            self.user,
            team=self.team,
        )

        response = execute_command(ast.ShowGrantsCommand(), self.user, team=self.team)

        assert len(response.results) == 1
        assert response.results[0][1] == "Revenue Dashboard"

    def test_show_grants_filtered_by_resource(self):
        execute_command(
            ast.GrantCommand(access_level="editor", resource="insight", target_type="default"),
            self.user,
            team=self.team,
        )
        execute_command(
            ast.GrantCommand(access_level="viewer", resource="dashboard", target_type="default"),
            self.user,
            team=self.team,
        )

        node = ast.ShowGrantsCommand(resource="insight")
        response = execute_command(node, self.user, team=self.team)

        assert len(response.results) == 1
        assert response.results[0][0] == "insight"

    def test_show_grants_filtered_by_role(self):
        execute_command(
            ast.GrantCommand(access_level="editor", resource="insight", target_type="role", target_name="Analysts"),
            self.user,
            team=self.team,
        )
        execute_command(
            ast.GrantCommand(access_level="viewer", resource="insight", target_type="default"),
            self.user,
            team=self.team,
        )

        node = ast.ShowGrantsCommand(filter_type="role", filter_name="Analysts")
        response = execute_command(node, self.user, team=self.team)

        assert len(response.results) == 1
        assert response.results[0][3] == "role"

    def test_access_control_requires_team(self):
        node = ast.GrantCommand(
            access_level="editor",
            resource="insight",
            target_type="default",
        )
        with self.assertRaises(QueryError):
            execute_command(node, self.user, team=None)
