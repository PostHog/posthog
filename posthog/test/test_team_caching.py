import json

from django.core.cache import cache
from django.test import TestCase

from posthog.models import Organization, Team
from posthog.models.team.team_caching import FIVE_DAYS, get_cached_team, get_or_set_cached_team


class TestModelCache(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_save_updates_cache(self):
        api_token = "test_token"
        org = Organization.objects.create(name="org name")

        initial_team = get_cached_team(api_token)
        assert not initial_team

        team = Team.objects.create(
            organization=org,
            api_token=api_token,
            test_account_filters=[],
        )

        cached_team = get_cached_team(api_token)
        assert cached_team is not None
        assert not cached_team.session_recording_opt_in
        assert cached_team.api_token == api_token
        assert cached_team.uuid == str(team.uuid)
        assert cached_team.id == team.id
        assert cached_team.name == "Default Project"

        team.name = "New name"
        team.session_recording_opt_in = True
        team.save()

        cached_team = get_cached_team(api_token)
        assert cached_team is not None
        assert cached_team.session_recording_opt_in
        assert cached_team.api_token == api_token
        assert cached_team.uuid == str(team.uuid)
        assert cached_team.id == team.id
        assert cached_team.name == "New name"

        team.delete()
        cached_team = get_cached_team(api_token)
        assert cached_team is None

    def test_outdated_cache_value_is_ignored(self):
        api_token = "test_token"
        org = Organization.objects.create(name="org name")
        team = Team.objects.create(
            organization=org,
            api_token=api_token,
            test_account_filters=[],
        )

        cache.set(f"team_token:{api_token}", json.dumps({"id": team.id}), FIVE_DAYS)

        # Invalid team is ignored
        loaded_team = get_cached_team(api_token)
        assert not loaded_team

        # Correct team is loaded
        loaded_team = get_or_set_cached_team(api_token)
        assert loaded_team

        # Now the valid cached value works
        loaded_team = get_cached_team(api_token)
        assert loaded_team
