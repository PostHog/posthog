from posthog.test.base import BaseTest

from django.core.management import call_command

from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestSyncFeatureFlags(BaseTest):
    def test_syncs_desktop_flags_and_is_idempotent(self) -> None:
        existing_filters = {
            "groups": [{"properties": [], "rollout_percentage": 25}],
            "payloads": {"true": '{"layout": "compact"}'},
        }
        FeatureFlag.objects.create(
            team=self.team,
            name="Existing desktop flag",
            key="loops",
            created_by=self.user,
            active=False,
            filters=existing_filters,
        )

        call_command("sync_feature_flags")

        loops = FeatureFlag.objects.get(team=self.team, key="loops")
        assert not loops.active
        assert loops.filters == existing_filters

        bluebird = FeatureFlag.objects.get(team=self.team, key="project-bluebird")
        assert bluebird.active
        assert bluebird.filters["groups"][0]["rollout_percentage"] == 100

        bedrock = FeatureFlag.objects.get(team=self.team, key="bedrock-llm-gateway")
        assert bedrock.filters["multivariate"]["variants"] == [
            {"key": "test", "name": "Test", "rollout_percentage": 0},
            {"key": "control", "name": "Control", "rollout_percentage": 100},
        ]

        bluebird.deleted = True
        bluebird.active = False
        bluebird.save(update_fields=["deleted", "active"])
        count = FeatureFlag.objects_including_soft_deleted.filter(team=self.team).count()

        call_command("sync_feature_flags")

        bluebird.refresh_from_db()
        assert not bluebird.deleted
        assert bluebird.active
        assert FeatureFlag.objects_including_soft_deleted.filter(team=self.team).count() == count
