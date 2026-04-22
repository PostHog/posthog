from posthog.test.base import BaseTest

from posthog.models import FeatureFlag


class TestFeatureFlagManager(BaseTest):
    def test_default_manager_excludes_soft_deleted_flags(self):
        FeatureFlag.objects.create(team=self.team, key="live", created_by=self.user)
        deleted_flag = FeatureFlag.objects_including_soft_deleted.create(
            team=self.team, key="deleted", created_by=self.user, deleted=True
        )

        assert FeatureFlag.objects.filter(team=self.team).count() == 1
        assert FeatureFlag.objects_including_soft_deleted.filter(team=self.team).count() == 2

        with self.assertRaises(FeatureFlag.DoesNotExist):
            FeatureFlag.objects.get(pk=deleted_flag.pk)
        assert FeatureFlag.objects_including_soft_deleted.get(pk=deleted_flag.pk) == deleted_flag
