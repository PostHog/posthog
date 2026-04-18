from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from posthog.models.person import Person
from posthog.tasks.feature_flags import cleanup_stale_hash_key_overrides
from posthog.tasks.test.utils import PushGatewayTaskTestMixin


class TestCleanupStaleHashKeyOverrides(PushGatewayTaskTestMixin, BaseTest):
    def _create_person(self, distinct_id: str = "test-person") -> Person:
        return Person.objects.create(team=self.team, distinct_ids=[distinct_id])

    def _create_flag(self, key: str, deleted: bool = False, active: bool = True) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            created_by=self.user,
            deleted=deleted,
            active=active,
            ensure_experience_continuity=True,
        )

    def _create_override(self, person: Person, flag_key: str, team=None) -> FeatureFlagHashKeyOverride:
        return FeatureFlagHashKeyOverride.objects.create(
            team=team or self.team,
            person=person,
            feature_flag_key=flag_key,
            hash_key="anon-id-123",
        )

    @parameterized.expand(
        [
            ("deleted_flag_overrides_cleaned", True, False, 0),
            ("active_flag_overrides_preserved", False, True, 1),
            ("inactive_but_not_deleted_preserved", False, False, 1),
        ]
    )
    def test_cleanup_based_on_flag_state(self, _name: str, deleted: bool, active: bool, expected_count: int) -> None:
        person = self._create_person()
        self._create_flag("test-flag", deleted=deleted, active=active)
        self._create_override(person, "test-flag")

        cleanup_stale_hash_key_overrides()

        self.assertEqual(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="test-flag").count(),
            expected_count,
        )

    def test_cross_team_isolation(self) -> None:
        from posthog.models.organization import Organization
        from posthog.models.team import Team

        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")

        person_a = self._create_person("person-a")
        person_b = Person.objects.create(team=other_team, distinct_ids=["person-b"])

        self._create_flag("shared-key", deleted=True)
        FeatureFlag.objects.create(
            team=other_team,
            key="shared-key",
            created_by=self.user,
            deleted=False,
            active=True,
            ensure_experience_continuity=True,
        )

        self._create_override(person_a, "shared-key", team=self.team)
        self._create_override(person_b, "shared-key", team=other_team)

        cleanup_stale_hash_key_overrides()

        self.assertEqual(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="shared-key").count(),
            0,
        )
        self.assertEqual(
            FeatureFlagHashKeyOverride.objects.filter(team=other_team, feature_flag_key="shared-key").count(),
            1,
        )

    def test_no_deleted_flags_is_noop(self) -> None:
        person = self._create_person()
        self._create_flag("active-flag", deleted=False)
        self._create_override(person, "active-flag")

        cleanup_stale_hash_key_overrides()

        self.assertEqual(FeatureFlagHashKeyOverride.objects.filter(team=self.team).count(), 1)

    def test_override_for_unknown_flag_key_preserved(self) -> None:
        person = self._create_person()
        self._create_override(person, "nonexistent-flag")

        cleanup_stale_hash_key_overrides()

        self.assertEqual(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="nonexistent-flag").count(),
            1,
        )

    def test_reports_metric(self) -> None:
        person = self._create_person()
        self._create_flag("deleted-flag", deleted=True)
        self._create_override(person, "deleted-flag")

        cleanup_stale_hash_key_overrides()

        metric_value = self.registry.get_sample_value("posthog_cleanup_stale_hash_key_overrides_deleted")
        self.assertEqual(metric_value, 1)
