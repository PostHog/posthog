from unittest.mock import MagicMock, patch

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.personal_api_key_utils import calculate_scope_change_logs
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestPersonalAPIKeyActivityLogging(ActivityLogTestHelper):
    def test_personal_api_key_creation_activity_logging(self):
        api_key = self.create_personal_api_key(label="Test API Key")
        api_key_id = api_key["id"]

        logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="created")
        self.assertTrue(len(logs) >= 1)

        log = logs.first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.scope, "PersonalAPIKey")
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(api_key_id))
        self.assertEqual(log.user, self.user)
        self.assertFalse(log.was_impersonated or False)
        self.assertFalse(log.is_system or False)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertIsNone(log.team_id)  # Global keys should have no team_id

        self.assertIsNotNone(log.detail)
        detail = log.detail
        assert detail is not None
        self.assertEqual(detail["name"], "Test API Key")
        self.assertIsNotNone(detail.get("context"))

        context = detail["context"]
        assert context is not None
        self.assertEqual(context["user_id"], self.user.id)
        self.assertEqual(context["user_email"], self.user.email)
        self.assertEqual(context["organization_name"], self.organization.name)
        self.assertEqual(context["team_name"], "Unknown Project")  # Global keys have no team context

    def test_personal_api_key_update_activity_logging(self):
        api_key = self.create_personal_api_key(label="Original API Key")
        api_key_id = api_key["id"]

        self.update_personal_api_key(api_key_id, {"label": "Updated API Key"})

        update_logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="updated")
        self.assertTrue(len(update_logs) >= 1)

        update_log = update_logs.first()
        self.assertIsNotNone(update_log)
        assert update_log is not None
        self.assertIsNotNone(update_log.detail)
        assert update_log.detail is not None

        changes = update_log.detail.get("changes", [])
        label_change = next((change for change in changes if change.get("field") == "label"), None)
        self.assertIsNotNone(label_change)
        assert label_change is not None
        self.assertEqual(label_change["action"], "changed")
        self.assertEqual(label_change["before"], "Original API Key")
        self.assertEqual(label_change["after"], "Updated API Key")

    def test_personal_api_key_scopes_update_activity_logging(self):
        api_key = self.create_personal_api_key(label="Scoped API Key")
        api_key_id = api_key["id"]

        self.update_personal_api_key(api_key_id, {"scopes": ["insight:read", "insight:write"]})

        update_logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="updated")
        self.assertTrue(len(update_logs) >= 1)

        update_log = update_logs.first()
        self.assertIsNotNone(update_log)
        assert update_log is not None
        self.assertIsNotNone(update_log.detail)
        assert update_log.detail is not None

        changes = update_log.detail.get("changes", [])
        scopes_change = next((change for change in changes if change.get("field") == "scopes"), None)
        self.assertIsNotNone(scopes_change)
        assert scopes_change is not None
        self.assertEqual(scopes_change["action"], "changed")
        self.assertEqual(scopes_change["before"], ["*"])
        self.assertEqual(scopes_change["after"], ["insight:read", "insight:write"])

    def test_personal_api_key_deletion_activity_logging(self):
        api_key = self.create_personal_api_key(label="To Delete API Key")
        api_key_id = api_key["id"]

        response = self.client.delete(f"/api/personal_api_keys/{api_key_id}/")
        self.assertEqual(response.status_code, 204)

        delete_logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="deleted")
        self.assertTrue(len(delete_logs) >= 1)

        delete_log = delete_logs.first()
        self.assertIsNotNone(delete_log)
        assert delete_log is not None
        self.assertEqual(delete_log.scope, "PersonalAPIKey")
        self.assertEqual(delete_log.activity, "deleted")
        self.assertEqual(delete_log.item_id, str(api_key_id))

        self.assertIsNotNone(delete_log.detail)
        detail = delete_log.detail
        assert detail is not None
        self.assertEqual(detail["name"], "To Delete API Key")
        self.assertIsNotNone(detail.get("context"))

        context = detail["context"]
        assert context is not None
        self.assertEqual(context["user_id"], self.user.id)
        self.assertEqual(context["user_email"], self.user.email)

    def test_personal_api_key_roll_activity_logging(self):
        api_key = self.create_personal_api_key(label="Rollable API Key")
        api_key_id = api_key["id"]

        response = self.client.post(f"/api/personal_api_keys/{api_key_id}/roll/")
        self.assertEqual(response.status_code, 200)

        update_logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="updated")
        self.assertTrue(len(update_logs) >= 1)

        update_log = update_logs.first()
        self.assertIsNotNone(update_log)
        assert update_log is not None
        self.assertIsNotNone(update_log.detail)
        assert update_log.detail is not None

        changes = update_log.detail.get("changes", [])
        self.assertTrue(len(changes) >= 0)

    def test_personal_api_key_activity_log_properties(self):
        api_key = self.create_personal_api_key(label="Properties Test Key")
        api_key_id = api_key["id"]

        logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="created")
        self.assertTrue(len(logs) >= 1)

        log = logs.first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.scope, "PersonalAPIKey")
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(api_key_id))
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.user, self.user)
        self.assertFalse(log.was_impersonated or False)
        self.assertFalse(log.is_system or False)

        self.assertIsNotNone(log.detail)
        detail = log.detail
        assert detail is not None
        self.assertEqual(detail["name"], "Properties Test Key")
        self.assertIsNotNone(detail.get("context"))
        self.assertIsNotNone(detail.get("changes"))

    def test_personal_api_key_scoped_organizations_logging(self):
        second_org = Organization.objects.create(name="Second Organization")
        self.user.join(organization=second_org)

        api_key = self.create_personal_api_key(
            label="Scoped to Orgs API Key", scoped_organizations=[str(self.organization.id), str(second_org.id)]
        )
        api_key_id = api_key["id"]

        logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="created")
        self.assertEqual(len(logs), 2)

        org_ids = {str(log.organization_id) for log in logs}
        expected_org_ids = {str(self.organization.id), str(second_org.id)}
        self.assertEqual(org_ids, expected_org_ids)

        for log in logs:
            self.assertIsNone(log.team_id)
            assert log.detail is not None
            self.assertEqual(log.detail["context"]["team_name"], "Unknown Project")

    def test_personal_api_key_scoped_teams_logging(self):
        second_org = Organization.objects.create(name="Second Organization")
        self.user.join(organization=second_org)
        second_team = Team.objects.create(organization=second_org, name="Second Team")

        api_key = self.create_personal_api_key(
            label="Scoped to Teams API Key", scoped_teams=[self.team.id, second_team.id]
        )
        api_key_id = api_key["id"]

        logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="created")
        self.assertEqual(len(logs), 2)

        org_ids = {str(log.organization_id) for log in logs}
        expected_org_ids = {str(self.organization.id), str(second_org.id)}
        self.assertEqual(org_ids, expected_org_ids)

        team_ids = {log.team_id for log in logs}
        expected_team_ids = {self.team.id, second_team.id}
        self.assertEqual(team_ids, expected_team_ids)

        for log in logs:
            self.assertIsNotNone(log.team_id)
            assert log.detail is not None
            if log.team_id == self.team.id:
                self.assertEqual(log.detail["context"]["team_name"], self.team.name)
            elif log.team_id == second_team.id:
                self.assertEqual(log.detail["context"]["team_name"], second_team.name)

    def test_activity_log_api_returns_personal_api_key_logs(self):
        api_key = self.create_personal_api_key(label="API Test Key")
        api_key_id = api_key["id"]

        logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="created")
        self.assertTrue(len(logs) >= 1)

        response = self.client.get(f"/api/projects/{self.team.id}/activity_log?scope=PersonalAPIKey")
        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertTrue(len(data["results"]) >= 1)
        found_log = None
        for result in data["results"]:
            if result["scope"] == "PersonalAPIKey" and result["item_id"] == api_key_id:
                found_log = result
                break

        self.assertIsNotNone(found_log)
        assert found_log is not None
        self.assertEqual(found_log["activity"], "created")
        self.assertEqual(found_log["detail"]["name"], "API Test Key")

    def test_team_scoped_api_key_creation_activity_logging(self):
        """Test that team-scoped API keys create logs with correct team_id."""
        api_key = self.create_personal_api_key(label="Team Scoped Key", scoped_teams=[self.team.id])
        api_key_id = api_key["id"]

        logs = ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(api_key_id), activity="created")
        self.assertEqual(len(logs), 1)

        log = logs.first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.scope, "PersonalAPIKey")
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(api_key_id))
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.team_id, self.team.id)

        self.assertIsNotNone(log.detail)
        detail = log.detail
        assert detail is not None
        self.assertEqual(detail["name"], "Team Scoped Key")
        self.assertIsNotNone(detail.get("context"))

        context = detail["context"]
        assert context is not None
        self.assertEqual(context["user_id"], self.user.id)
        self.assertEqual(context["user_email"], self.user.email)
        self.assertEqual(context["organization_name"], self.organization.name)
        self.assertEqual(context["team_name"], self.team.name)


class TestPersonalAPIKeyScopeChanges(ActivityLogTestHelper):
    def _create_api_key(self, scoped_teams=None, scoped_organizations=None, label="Test Key"):
        api_key = MagicMock()
        api_key.scoped_teams = scoped_teams or []
        api_key.scoped_organizations = scoped_organizations or []
        # Create a mock user instead of using the real test user
        mock_user = MagicMock()
        mock_user.id = 999
        api_key.user = mock_user
        api_key.label = label
        return api_key

    def _create_mock_teams(self):
        teams = {}
        for team_id, org_id in [(1, "org-a"), (3, "org-b"), (4, "org-b"), (5, "org-c")]:
            team = MagicMock()
            team.id = team_id
            team.organization_id = org_id
            teams[team_id] = team
        return teams

    def _mock_team_filter(self, teams_dict):
        def filter_teams(*args, **kwargs):
            if "pk__in" in kwargs:
                filtered_teams = [teams_dict[team_id] for team_id in kwargs["pk__in"] if team_id in teams_dict]
                mock_result = MagicMock()
                mock_result.select_related.return_value = filtered_teams
                return mock_result
            elif "organization_id__in" in kwargs:
                org_ids = kwargs["organization_id__in"]
                filtered_teams = [team for team in teams_dict.values() if team.organization_id in org_ids]
                mock_result = MagicMock()

                def values_method(*args, **kwargs):
                    if args == ("id", "organization_id") or args == ("organization_id", "id"):
                        return [{"id": team.id, "organization_id": team.organization_id} for team in filtered_teams]
                    elif args == ("organization_id",):
                        values_result = MagicMock()

                        def annotate(**annotations):
                            org_counts = {}
                            for team in filtered_teams:
                                org_id = team.organization_id
                                if org_id not in org_counts:
                                    org_counts[org_id] = 0
                                org_counts[org_id] += 1

                            return [
                                {"organization_id": org_id, "team_count": count} for org_id, count in org_counts.items()
                            ]

                        values_result.annotate = annotate
                        return values_result
                    else:
                        return [{"id": team.id, "organization_id": team.organization_id} for team in filtered_teams]

                mock_result.values = values_method
                return mock_result
            else:
                mock_result = MagicMock()
                mock_result.select_related.return_value = []
                return mock_result

        return filter_teams

    def _mock_user_permissions(self, org_memberships):
        def mock_user_perms_constructor(user):
            mock_perms = MagicMock()
            mock_perms.organization_memberships.keys.return_value = org_memberships
            return mock_perms

        return mock_user_perms_constructor

    def _assert_logs_count(self, logs, expected_created=0, expected_revoked=0):
        created_logs = [log for log in logs if log["activity"] == "created"]
        revoked_logs = [log for log in logs if log["activity"] == "revoked"]

        assert len(created_logs) == expected_created
        assert len(revoked_logs) == expected_revoked

        updated_logs = [log for log in logs if log["activity"] == "updated"]
        assert len(updated_logs) == 0

    def _assert_log_locations(self, logs, expected_locations):
        actual_locations = {(log["organization_id"], log["team_id"]) for log in logs}
        expected_set = {(loc[0], loc[1]) for loc in expected_locations}
        assert actual_locations == expected_set

    def _assert_activity_locations(self, logs, activity, expected_locations):
        filtered_logs = [log for log in logs if log["activity"] == activity]
        actual_locations = {(log["organization_id"], log["team_id"]) for log in filtered_logs}
        expected_set = {(loc[0], loc[1]) for loc in expected_locations}
        assert actual_locations == expected_set

    def test_global_to_org_scoped(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            # Patch UserPermissions where it's imported in personal_api_key_utils
            with patch(
                "posthog.models.activity_logging.personal_api_key_utils.UserPermissions",
                side_effect=self._mock_user_permissions(["org-a", "org-b", "org-c"]),
            ):
                before = self._create_api_key()
                after = self._create_api_key(scoped_organizations=["org-a", "org-b"])
                logs = calculate_scope_change_logs(before, after, [])

                self._assert_logs_count(logs, expected_created=0, expected_revoked=1)
                self._assert_activity_locations(logs, "revoked", [("org-c", None)])

    def test_global_to_team_scoped(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            with patch(
                "posthog.models.activity_logging.personal_api_key_utils.UserPermissions",
                side_effect=self._mock_user_permissions(["org-a", "org-b", "org-c"]),
            ):
                before = self._create_api_key()
                after = self._create_api_key(scoped_teams=[1, 3])
                logs = calculate_scope_change_logs(before, after, [])

                self._assert_logs_count(logs, expected_created=2, expected_revoked=3)
                self._assert_activity_locations(logs, "created", [("org-a", 1), ("org-b", 3)])
                self._assert_activity_locations(logs, "revoked", [("org-a", None), ("org-b", None), ("org-c", None)])

    def test_org_scoped_to_global(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            with patch(
                "posthog.models.activity_logging.personal_api_key_utils.UserPermissions",
                side_effect=self._mock_user_permissions(["org-a", "org-b", "org-c"]),
            ):
                before = self._create_api_key(scoped_organizations=["org-a", "org-b"])
                after = self._create_api_key()
                logs = calculate_scope_change_logs(before, after, [])

                self._assert_logs_count(logs, expected_created=1, expected_revoked=0)
                self._assert_activity_locations(logs, "created", [("org-c", None)])

    def test_org_scoped_to_different_orgs(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_organizations=["org-a", "org-b"])
            after = self._create_api_key(scoped_organizations=["org-b", "org-c"])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=1, expected_revoked=1)
            self._assert_activity_locations(logs, "created", [("org-c", None)])
            self._assert_activity_locations(logs, "revoked", [("org-a", None)])

    def test_org_scoped_to_team_scoped(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_organizations=["org-a", "org-b"])
            after = self._create_api_key(scoped_teams=[1])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=0, expected_revoked=1)
            self._assert_activity_locations(logs, "revoked", [("org-b", None)])

    def test_team_scoped_to_global(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            with patch(
                "posthog.models.activity_logging.personal_api_key_utils.UserPermissions",
                side_effect=self._mock_user_permissions(["org-a", "org-b", "org-c"]),
            ):
                before = self._create_api_key(scoped_teams=[1, 3])
                after = self._create_api_key()
                logs = calculate_scope_change_logs(before, after, [])

                self._assert_logs_count(logs, expected_created=2, expected_revoked=2)
                self._assert_activity_locations(logs, "created", [("org-b", None), ("org-c", None)])
                self._assert_activity_locations(logs, "revoked", [("org-a", None), ("org-b", 3)])

    def test_team_scoped_to_org_scoped(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[1, 3])
            after = self._create_api_key(scoped_organizations=["org-a", "org-b"])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=1, expected_revoked=2)
            self._assert_activity_locations(logs, "created", [("org-b", None)])
            self._assert_activity_locations(logs, "revoked", [("org-a", None), ("org-b", 3)])

    def test_team_scoped_to_different_teams(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[1, 3])
            after = self._create_api_key(scoped_teams=[3, 4])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=1, expected_revoked=1)
            self._assert_activity_locations(logs, "created", [("org-b", 4)])
            self._assert_activity_locations(logs, "revoked", [("org-a", None)])

    def test_global_no_scope_change(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            with patch(
                "posthog.models.activity_logging.personal_api_key_utils.UserPermissions",
                side_effect=self._mock_user_permissions(["org-a", "org-b", "org-c"]),
            ):
                before = self._create_api_key()
                after = self._create_api_key()
                logs = calculate_scope_change_logs(before, after, [])

                self._assert_logs_count(logs, expected_created=0, expected_revoked=0)

    def test_org_scoped_no_scope_change(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_organizations=["org-a", "org-b"])
            after = self._create_api_key(scoped_organizations=["org-a", "org-b"])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=0, expected_revoked=0)

    def test_team_scoped_no_scope_change(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[1, 3])
            after = self._create_api_key(scoped_teams=[1, 3])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=0, expected_revoked=0)

    def test_cross_organization_team_changes(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[1, 3, 4])
            after = self._create_api_key(scoped_teams=[1, 5])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=1, expected_revoked=1)
            self._assert_activity_locations(logs, "created", [("org-c", 5)])
            self._assert_activity_locations(logs, "revoked", [("org-b", None)])

    def test_org_level_to_mixed_teams_across_orgs(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_organizations=["org-a", "org-b"])
            after = self._create_api_key(scoped_teams=[1, 3, 4, 5])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=1, expected_revoked=0)
            self._assert_activity_locations(logs, "created", [("org-c", 5)])

    def test_invalid_state_transitions(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[999, 1000])
            after = self._create_api_key(scoped_organizations=["org-a"])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=1, expected_revoked=0)
            self._assert_activity_locations(logs, "created", [("org-a", None)])

    def test_single_team_org_removal(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[1, 5])
            after = self._create_api_key(scoped_teams=[1])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=0, expected_revoked=1)
            self._assert_activity_locations(logs, "revoked", [("org-c", None)])

    def test_team_to_global_mixed_org_types(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            with patch(
                "posthog.models.activity_logging.personal_api_key_utils.UserPermissions",
                side_effect=self._mock_user_permissions(["org-a", "org-b", "org-c"]),
            ):
                before = self._create_api_key(scoped_teams=[1, 3])
                after = self._create_api_key()
                logs = calculate_scope_change_logs(before, after, [])

                self._assert_logs_count(logs, expected_created=2, expected_revoked=2)
                self._assert_activity_locations(logs, "created", [("org-b", None), ("org-c", None)])
                self._assert_activity_locations(logs, "revoked", [("org-a", None), ("org-b", 3)])

    def test_complete_org_team_revocation(self):
        teams = self._create_mock_teams()

        with patch.object(Team.objects, "filter", side_effect=self._mock_team_filter(teams)):
            before = self._create_api_key(scoped_teams=[1, 3, 4])
            after = self._create_api_key(scoped_teams=[1])
            logs = calculate_scope_change_logs(before, after, [])

            self._assert_logs_count(logs, expected_created=0, expected_revoked=1)
            self._assert_activity_locations(logs, "revoked", [("org-b", None)])
