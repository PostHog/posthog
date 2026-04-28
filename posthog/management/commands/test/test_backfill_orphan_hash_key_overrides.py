from io import StringIO

from posthog.test.base import APIBaseTest, _create_person, flush_persons_and_events

from django.core.management import call_command

from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from posthog.models.organization import Organization
from posthog.models.team import Team


class TestBackfillOrphanHashKeyOverrides(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.person = _create_person(team=self.team, distinct_ids=["d1"], properties={})
        flush_persons_and_events()

    def test_deletes_rows_whose_key_does_not_match_any_flag(self) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            key="kept-key",
            name="Kept",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        # Override row with a key that exists -> kept.
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="kept-key", hash_key="hk-1"
        )
        # Override row with a key that no longer matches any flag -> orphan, deleted.
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="orphan-key", hash_key="hk-2"
        )

        call_command(
            "backfill_orphan_hash_key_overrides",
            "--team-id",
            str(self.team.id),
            "--sleep-between-batches",
            "0",
            stdout=StringIO(),
        )

        keys = sorted(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        assert keys == ["kept-key"]

    def test_dry_run_does_not_delete(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="orphan-key", hash_key="hk-1"
        )

        call_command(
            "backfill_orphan_hash_key_overrides",
            "--team-id",
            str(self.team.id),
            "--dry-run",
            "--sleep-between-batches",
            "0",
            stdout=StringIO(),
        )

        assert FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="orphan-key").exists()

    def test_keeps_soft_deleted_flag_keys(self) -> None:
        """A soft-deleted flag's key (with the ``:deleted:<id>`` suffix) is
        still a current key in the team — override rows under that key are
        not orphans and must survive the sweep."""
        soft_deleted_flag = FeatureFlag.objects.create(
            team=self.team,
            key="something:deleted:42",
            name="Soft-deleted",
            created_by=self.user,
            deleted=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key=soft_deleted_flag.key, hash_key="hk-1"
        )

        call_command(
            "backfill_orphan_hash_key_overrides",
            "--team-id",
            str(self.team.id),
            "--sleep-between-batches",
            "0",
            stdout=StringIO(),
        )

        assert FeatureFlagHashKeyOverride.objects.filter(
            team=self.team, feature_flag_key=soft_deleted_flag.key
        ).exists()

    def test_does_not_touch_other_teams(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create_with_data(initiating_user=self.user, organization=other_org, name="Other")
        other_person = _create_person(team=other_team, distinct_ids=["d2"], properties={})
        flush_persons_and_events()

        # Other team has no flag for "orphan-key", but the sweep is scoped to self.team.
        FeatureFlagHashKeyOverride.objects.create(
            team=other_team, person=other_person, feature_flag_key="orphan-key", hash_key="hk-other"
        )
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="orphan-key", hash_key="hk-self"
        )

        call_command(
            "backfill_orphan_hash_key_overrides",
            "--team-id",
            str(self.team.id),
            "--sleep-between-batches",
            "0",
            stdout=StringIO(),
        )

        assert not FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="orphan-key").exists()
        assert FeatureFlagHashKeyOverride.objects.filter(team=other_team, feature_flag_key="orphan-key").exists()
