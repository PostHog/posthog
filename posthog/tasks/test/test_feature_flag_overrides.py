from posthog.test.base import APIBaseTest, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.db import DatabaseError

from parameterized import parameterized

from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.tasks.feature_flags import delete_hash_key_overrides_for_flag, rewrite_hash_key_overrides_for_flag


class TestRewriteHashKeyOverridesForFlag(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.person = _create_person(team=self.team, distinct_ids=["d1"], properties={})
        flush_persons_and_events()

    @parameterized.expand(
        [
            # (label, initial rows as [(feature_flag_key, hash_key)], old_key,
            #  new_key, expected rows after as [(feature_flag_key, hash_key)],
            #  run_twice — exercises idempotency)
            ("normal_rename", [("old-key", "hk-1")], "old-key", "new-key", [("new-key", "hk-1")], False),
            ("same_key_is_a_no_op", [("same", "hk-1")], "same", "same", [("same", "hk-1")], False),
            (
                "second_run_is_idempotent",
                [("old-key", "hk-1")],
                "old-key",
                "new-key",
                [("new-key", "hk-1")],
                True,
            ),
            (
                "leaves_other_keys_untouched",
                [("target-key", "hk-1"), ("other-key", "hk-2")],
                "target-key",
                "renamed",
                [("other-key", "hk-2"), ("renamed", "hk-1")],
                False,
            ),
            (
                "old_key_absent_is_a_no_op",
                [("untouched", "hk-1")],
                "missing-key",
                "new-key",
                [("untouched", "hk-1")],
                False,
            ),
        ]
    )
    def test_rewrite_scenarios(
        self,
        _name: str,
        initial_rows: list[tuple[str, str]],
        old_key: str,
        new_key: str,
        expected_rows: list[tuple[str, str]],
        run_twice: bool,
    ) -> None:
        for fk, hk in initial_rows:
            FeatureFlagHashKeyOverride.objects.create(
                team=self.team, person=self.person, feature_flag_key=fk, hash_key=hk
            )

        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key=old_key, new_key=new_key)
        if run_twice:
            rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key=old_key, new_key=new_key)

        actual = sorted(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", "hash_key")
        )
        assert actual == sorted(expected_rows)

    def test_does_not_touch_other_teams(self) -> None:
        """Cross-team scoping: a row with the same key in another team must
        survive the rewrite for ``self.team``."""
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create_with_data(initiating_user=self.user, organization=other_org, name="Other")
        other_person = _create_person(team=other_team, distinct_ids=["d2"], properties={})
        flush_persons_and_events()

        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="shared-key", hash_key="hk-self"
        )
        FeatureFlagHashKeyOverride.objects.create(
            team=other_team, person=other_person, feature_flag_key="shared-key", hash_key="hk-other"
        )

        rewrite_hash_key_overrides_for_flag(team_id=self.team.id, old_key="shared-key", new_key="renamed")

        self_keys = list(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", flat=True)
        )
        other_keys = list(
            FeatureFlagHashKeyOverride.objects.filter(team=other_team).values_list("feature_flag_key", flat=True)
        )
        assert self_keys == ["renamed"]
        assert other_keys == ["shared-key"]


class TestDeleteHashKeyOverridesForFlag(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.person = _create_person(team=self.team, distinct_ids=["d1"], properties={})
        flush_persons_and_events()

    @parameterized.expand(
        [
            # (label, initial rows as [(feature_flag_key, hash_key)], key_to_delete,
            #  expected surviving rows as [(feature_flag_key, hash_key)], run_twice)
            ("deletes_matching_rows", [("doomed", "hk-1")], "doomed", [], False),
            (
                "second_run_is_idempotent",
                [("doomed", "hk-1")],
                "doomed",
                [],
                True,
            ),
            (
                "leaves_other_keys_untouched",
                [("doomed", "hk-1"), ("surviving", "hk-2")],
                "doomed",
                [("surviving", "hk-2")],
                False,
            ),
            (
                "missing_key_is_a_no_op",
                [("untouched", "hk-1")],
                "missing-key",
                [("untouched", "hk-1")],
                False,
            ),
        ]
    )
    def test_delete_scenarios(
        self,
        _name: str,
        initial_rows: list[tuple[str, str]],
        key_to_delete: str,
        expected_rows: list[tuple[str, str]],
        run_twice: bool,
    ) -> None:
        for fk, hk in initial_rows:
            FeatureFlagHashKeyOverride.objects.create(
                team=self.team, person=self.person, feature_flag_key=fk, hash_key=hk
            )

        delete_hash_key_overrides_for_flag(team_id=self.team.id, key=key_to_delete)
        if run_twice:
            delete_hash_key_overrides_for_flag(team_id=self.team.id, key=key_to_delete)

        actual = sorted(
            FeatureFlagHashKeyOverride.objects.filter(team=self.team).values_list("feature_flag_key", "hash_key")
        )
        assert actual == sorted(expected_rows)

    def test_does_not_touch_other_teams(self) -> None:
        """Cross-team scoping: deleting overrides for ``(self.team, "doomed")``
        must leave another team's rows for the same key in place."""
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create_with_data(initiating_user=self.user, organization=other_org, name="Other")
        other_person = _create_person(team=other_team, distinct_ids=["d2"], properties={})
        flush_persons_and_events()

        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=self.person, feature_flag_key="doomed", hash_key="hk-self"
        )
        FeatureFlagHashKeyOverride.objects.create(
            team=other_team, person=other_person, feature_flag_key="doomed", hash_key="hk-other"
        )

        delete_hash_key_overrides_for_flag(team_id=self.team.id, key="doomed")

        assert not FeatureFlagHashKeyOverride.objects.filter(team=self.team, feature_flag_key="doomed").exists()
        assert FeatureFlagHashKeyOverride.objects.filter(team=other_team, feature_flag_key="doomed").exists()


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
    def test_pre_atomic_validation_failure_does_not_queue_task(self, mock_rewrite) -> None:
        """DRF validation runs before ``update()`` even enters its atomic block,
        so the on_commit callback was never registered. Guards against future
        regressions where a malformed request might still queue cleanup work.
        """
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
            data={"key": "renamed", "filters": {"groups": "not-a-list"}},
            content_type="application/json",
        )

        assert response.status_code == 400, response.content
        mock_rewrite.assert_not_called()

    @patch("posthog.tasks.feature_flags.rewrite_hash_key_overrides_for_flag.delay")
    def test_db_error_inside_atomic_rolls_back_and_drops_registered_callback(self, mock_rewrite) -> None:
        """Genuine rollback test: the on_commit callback is registered first
        (inside the atomic block), then the underlying ``FeatureFlag.save``
        raises a ``DatabaseError``. Django's contract is that on_commit
        callbacks registered against a transaction that ultimately rolls back
        must NOT execute. This test verifies that contract holds for our hook.
        """
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="original-key",
            name="Flag",
            created_by=self.user,
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        with patch.object(FeatureFlag, "save", side_effect=DatabaseError("simulated rollback")):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
                data={"key": "renamed-key"},
                content_type="application/json",
            )

        # The DatabaseError surfaces as a 500 — what matters here is that the
        # rewrite task delay() was never invoked despite on_commit being
        # registered before the failure.
        assert response.status_code >= 500, response.content
        mock_rewrite.assert_not_called()
