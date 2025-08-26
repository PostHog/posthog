from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from posthog.schema import PersonsOnEventsMode

from posthog.models import Dashboard, DashboardTile, Organization, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.models.project import Project
from posthog.models.team import get_team_in_cache, util

from .base import BaseTest

util.can_enable_actor_on_events = True


class TestModelCache(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_save_updates_cache(self):
        api_token = "test_token"
        org = Organization.objects.create(name="org name")

        initial_team = get_team_in_cache(api_token)
        self.assertIsNone(initial_team)

        team = Team.objects.create(
            organization=org,
            api_token=api_token,
            test_account_filters=[],
        )

        cached_team = get_team_in_cache(api_token)
        assert cached_team is not None
        self.assertEqual(cached_team.session_recording_opt_in, False)
        self.assertEqual(cached_team.api_token, api_token)
        self.assertEqual(cached_team.uuid, str(team.uuid))
        self.assertEqual(cached_team.id, team.id)
        self.assertEqual(cached_team.name, "Default project")

        team.name = "New name"
        team.session_recording_opt_in = True
        team.save()

        cached_team = get_team_in_cache(api_token)
        assert cached_team is not None
        self.assertEqual(cached_team.session_recording_opt_in, True)
        self.assertEqual(cached_team.api_token, api_token)
        self.assertEqual(cached_team.uuid, str(team.uuid))
        self.assertEqual(cached_team.id, team.id)
        self.assertEqual(cached_team.name, "New name")

        team.delete()
        cached_team = get_team_in_cache(api_token)
        assert cached_team is None


class TestTeam(BaseTest):
    def test_team_has_expected_defaults(self):
        team: Team = Team.objects.create(name="New Team", organization=self.organization)
        self.assertEqual(team.timezone, "UTC")
        self.assertEqual(team.data_attributes, ["data-attr"])
        self.assertEqual(team.autocapture_exceptions_opt_in, None)
        self.assertEqual(team.autocapture_web_vitals_opt_in, None)
        self.assertEqual(team.autocapture_web_vitals_allowed_metrics, None)
        self.assertEqual(team.autocapture_exceptions_errors_to_ignore, None)

    def test_create_team_with_test_account_filters(self):
        team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
        self.assertEqual(
            team.test_account_filters,
            [
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "key": "$host",
                    "operator": "not_regex",
                    "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                    "type": "event",
                },
            ],
        )

        # test generic emails
        user = User.objects.create(email="test@gmail.com")
        organization = Organization.objects.create()
        organization.members.set([user])
        team = Team.objects.create_with_data(initiating_user=self.user, organization=organization)
        self.assertEqual(
            team.test_account_filters,
            [
                {
                    "key": "$host",
                    "operator": "not_regex",
                    "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                    "type": "event",
                }
            ],
        )

    def test_create_team_sets_primary_dashboard(self):
        team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
        self.assertIsInstance(team.primary_dashboard, Dashboard)

        # Ensure insights are created and linked
        self.assertEqual(DashboardTile.objects.filter(dashboard=team.primary_dashboard).count(), 6)

    @mock.patch("posthoganalytics.feature_enabled", return_value=True)
    def test_team_on_cloud_uses_feature_flag_to_determine_person_on_events(self, mock_feature_enabled):
        with self.is_cloud(True):
            with override_instance_config("PERSON_ON_EVENTS_ENABLED", False):
                team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
                self.assertEqual(
                    team.person_on_events_mode, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
                )
                # called more than once when evaluating hogql
                mock_feature_enabled.assert_called_with(
                    "persons-on-events-v2-reads-enabled",
                    str(team.uuid),
                    groups={"organization": str(self.organization.id)},
                    group_properties={
                        "organization": {
                            "id": str(self.organization.id),
                            "created_at": self.organization.created_at,
                        }
                    },
                    only_evaluate_locally=True,
                    send_feature_flag_events=False,
                )

    @mock.patch("posthoganalytics.feature_enabled", return_value=False)
    def test_team_on_self_hosted_uses_instance_setting_to_determine_person_on_events(self, mock_feature_enabled):
        with self.is_cloud(False):
            with override_instance_config("PERSON_ON_EVENTS_V2_ENABLED", True):
                team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
                self.assertEqual(
                    team.person_on_events_mode, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
                )
                for args_list in mock_feature_enabled.call_args_list:
                    # It is ok if we check other feature flags, just not `persons-on-events-v2-reads-enabled`
                    assert args_list[0][0] != "persons-on-events-v2-reads-enabled"

            with override_instance_config("PERSON_ON_EVENTS_V2_ENABLED", False):
                team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
                self.assertEqual(team.person_on_events_mode, PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED)
                for args_list in mock_feature_enabled.call_args_list:
                    # It is ok if we check other feature flags, just not `persons-on-events-v2-reads-enabled`
                    assert args_list[0][0] != "persons-on-events-v2-reads-enabled"

    def test_each_team_gets_project_with_default_name_and_same_id(self):
        # Can be removed once environments are fully rolled out
        team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)

        project = Project.objects.filter(id=team.id).first()

        assert project is not None
        self.assertEqual(project.name, "Default project")

    def test_each_team_gets_project_with_custom_name_and_same_id(self):
        # Can be removed once environments are fully rolled out
        team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user, name="Hogflix")

        project = Project.objects.filter(id=team.id).first()

        assert project is not None
        self.assertEqual(project.organization, team.organization)
        self.assertEqual(project.name, "Hogflix")

    @mock.patch("posthog.models.project.Project.objects.create", side_effect=Exception)
    def test_team_not_created_if_project_creation_fails(self, mock_create):
        # Can be removed once environments are fully rolled out
        initial_team_count = Team.objects.count()
        initial_project_count = Project.objects.count()

        with self.assertRaises(Exception):
            Team.objects.create_with_data(organization=self.organization, initiating_user=self.user, name="Hogflix")

        self.assertEqual(Team.objects.count(), initial_team_count)
        self.assertEqual(Project.objects.count(), initial_project_count)

    def test_increment_id_sequence(self):
        initial = Team.objects.increment_id_sequence()
        subsequent = Team.objects.increment_id_sequence()

        self.assertEqual(subsequent, initial + 1)
