from posthog.test.base import APIBaseTest, _create_person, flush_persons_and_events
from unittest.mock import patch

from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from posthog.tasks.feature_flags import delete_hash_key_overrides_for_flag, rewrite_hash_key_overrides_for_flag


class TestRewriteHashKeyOverridesForFlag(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.person = _create_person(team=self.team, distinct_ids=["d1"], properties={})
        flush_persons_and_events()

    def test_rewrites_rows_for_team_and_old_key(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="old-key", hash_key="hk-1"
        )
        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key="old-key", new_key="new-key")

        rows = list(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        assert rows == ["new-key"]

    def test_no_op_when_old_key_equals_new_key(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="same", hash_key="hk-1"
        )
        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key="same", new_key="same")

        rows = list(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        assert rows == ["same"]

    def test_idempotent_second_run(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="old-key", hash_key="hk-1"
        )
        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key="old-key", new_key="new-key")
        # Re-running with the same args is a no-op (no rows under old-key anymore).
        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key="old-key", new_key="new-key")

        rows = list(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        assert rows == ["new-key"]

    def test_does_not_touch_other_teams_or_keys(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="target-key", hash_key="hk-1"
        )
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="other-key", hash_key="hk-2"
        )
        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key="target-key", new_key="renamed")

        keys = sorted(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        assert keys == ["other-key", "renamed"]


class TestDeleteHashKeyOverridesForFlag(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.person = _create_person(team=self.team, distinct_ids=["d1"], properties={})
        flush_persons_and_events()

    def test_deletes_rows_for_team_and_key(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="doomed-flag", hash_key="hk-1"
        )
        delete_hash_key_overrides_for_flag(team_id=self.team.id, key="doomed-flag")

        assert not FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="doomed-flag").exists()

    def test_idempotent_second_run(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="doomed-flag", hash_key="hk-1"
        )
        delete_hash_key_overrides_for_flag(team_id=self.team.id, key="doomed-flag")
        delete_hash_key_overrides_for_flag(team_id=self.team.id, key="doomed-flag")

        assert not FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="doomed-flag").exists()

    def test_does_not_touch_other_keys(self) -> None:
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="doomed-flag", hash_key="hk-1"
        )
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="surviving-flag", hash_key="hk-2"
        )
        delete_hash_key_overrides_for_flag(team_id=self.team.id, key="doomed-flag")

        keys = sorted(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        assert keys == ["surviving-flag"]


class TestSerializerHooksFireTasksOnCommit(APIBaseTest):
    """Serializer-level tests verifying ``transaction.on_commit`` queues the right
    cleanup task only when the transaction actually commits.
    """

    def setUp(self) -> None:
        super().setUp()
        self.person = _create_person(team=self.team, distinct_ids=["d1"], properties={})
        flush_persons_and_events()

    @patch("posthog.tasks.feature_flags.rewrite_hash_key_overrides_for_flag.delay")
    def test_rename_queues_rewrite_task_with_old_and_new_keys(self, mock_rewrite) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="original-key",
            name="Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            data={"key": "renamed-key"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        mock_rewrite.assert_called_once_with(team_id=self.team.id, old_key="original-key", new_key="renamed-key")

    @patch("posthog.tasks.feature_flags.rewrite_hash_key_overrides_for_flag.delay")
    def test_no_rewrite_task_when_key_unchanged(self, mock_rewrite) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="stable-key",
            name="Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            data={"name": "Renamed display only"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        mock_rewrite.assert_not_called()

    @patch("posthog.tasks.feature_flags.delete_hash_key_overrides_for_flag.delay")
    def test_soft_delete_queues_delete_task_with_original_key(self, mock_delete) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="to-be-deleted",
            name="Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            data={"deleted": True},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        # The serializer may rename the key to ``<key>:deleted:<id>`` if there are
        # soft-deleted experiments — the cleanup must still target the *original*
        # key under which the override rows were stored.
        mock_delete.assert_called_once_with(team_id=self.team.id, key="to-be-deleted")

    @patch("posthog.tasks.feature_flags.rewrite_hash_key_overrides_for_flag.delay")
    @patch("posthog.tasks.feature_flags.delete_hash_key_overrides_for_flag.delay")
    def test_soft_delete_does_not_also_queue_rewrite_task(self, mock_delete, mock_rewrite) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="to-be-deleted",
            name="Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            data={"deleted": True},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        mock_delete.assert_called_once()
        mock_rewrite.assert_not_called()

    @patch("posthog.tasks.feature_flags.rewrite_hash_key_overrides_for_flag.delay")
    def test_rollback_means_no_task_queued(self, mock_rewrite) -> None:
        """If the update raises after on_commit was registered, the task must not fire."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="original-key",
            name="Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Force a validation failure on update by sending an invalid filters shape
        # AFTER our rename hook would otherwise fire. The transaction wrapping
        # super().update() will roll back, and on_commit callbacks won't run.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            data={"key": "renamed", "filters": {"groups": "not-a-list"}},
            content_type="application/json",
        )

        assert response.status_code == 400, response.content
        mock_rewrite.assert_not_called()
