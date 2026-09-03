from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import AsyncDeletion, DeletionType, Organization, Team
from posthog.models.async_deletion.delete_cohorts import CohortDeleteTarget, _collapse, sweep_cohort_deletions

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class TestCollapseCohortDeletions(TestCase):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="test")
        self.team = Team.objects.create(organization=self.organization)

    def _queue(self, deletion_type: DeletionType, *keys: str, team_id: int | None = None) -> None:
        AsyncDeletion.objects.bulk_create(
            AsyncDeletion(deletion_type=deletion_type, team_id=team_id or self.team.pk, key=key) for key in keys
        )

    @parameterized.expand(
        [
            # `posthog/api/cohort.py` appends the team id when the row is for a team other than the
            # cohort's own, so a key can carry three parts. Unpacking it into two raised ValueError
            # and took the whole pass with it.
            ("team_scoped_three_part_key", ["7_3_5512"], 7, None),
            ("plain_two_part_key", ["7_3"], 7, None),
            # A cohort that was never calculated writes its version as the literal "None".
            ("uncalculated_version", ["7_None"], 7, None),
            ("mixed_shapes_one_cohort", ["7_1", "7_2_5512", "7_None"], 7, None),
        ]
    )
    def test_full_deletion_keys_collapse_to_one_target(self, _name, keys, cohort_id, _unused):
        self._queue(DeletionType.Cohort_full, *keys)

        targets = _collapse(DeletionType.Cohort_full)

        assert targets == [CohortDeleteTarget(team_id=self.team.pk, cohort_id=cohort_id, below_version=None)]

    @parameterized.expand(
        [
            # OR of `version < Vi` is `version < max(Vi)`, so the bound must be the largest.
            ("ascending", ["9_1", "9_2", "9_7"], 7),
            ("descending", ["9_7", "9_2", "9_1"], 7),
            ("team_scoped_keys_carry_versions_too", ["9_3_5512", "9_11_5513"], 11),
            ("single", ["9_4"], 4),
        ]
    )
    def test_stale_deletions_collapse_to_the_highest_version(self, _name, keys, expected_bound):
        self._queue(DeletionType.Cohort_stale, *keys)

        targets = _collapse(DeletionType.Cohort_stale)

        assert targets == [CohortDeleteTarget(team_id=self.team.pk, cohort_id=9, below_version=expected_bound)]

    def test_one_cohort_queued_for_many_teams_stays_one_target_per_team(self):
        other = Team.objects.create(organization=self.organization)
        # The shape that made the queue unbounded: one deleted cohort, one row per team that saw it.
        self._queue(DeletionType.Cohort_full, *[f"12_{v}" for v in range(50)])
        self._queue(DeletionType.Cohort_full, *[f"12_{v}_{other.pk}" for v in range(50)], team_id=other.pk)

        targets = _collapse(DeletionType.Cohort_full)

        assert sorted(targets, key=lambda t: t.team_id) == sorted(
            [
                CohortDeleteTarget(team_id=self.team.pk, cohort_id=12, below_version=None),
                CohortDeleteTarget(team_id=other.pk, cohort_id=12, below_version=None),
            ],
            key=lambda t: t.team_id,
        )

    def test_verified_deletions_are_not_swept_again(self):
        self._queue(DeletionType.Cohort_full, "3_1", "4_1")
        AsyncDeletion.objects.filter(key="3_1").update(delete_verified_at="2026-01-01T00:00:00Z")

        assert _collapse(DeletionType.Cohort_full) == [
            CohortDeleteTarget(team_id=self.team.pk, cohort_id=4, below_version=None)
        ]

    def test_max_cohorts_caps_targets_and_leaves_the_rest_queued(self):
        self._queue(DeletionType.Cohort_full, *[f"{cohort}_1" for cohort in range(10)])

        targets = _collapse(DeletionType.Cohort_full, limit=3)

        assert [target.cohort_id for target in targets] == [0, 1, 2]
        assert AsyncDeletion.objects.filter(delete_verified_at__isnull=True).count() == 10

    @parameterized.expand([("no_underscore", "451"), ("not_a_number", "cohort_3"), ("empty", "")])
    def test_keys_that_name_no_cohort_are_skipped_rather_than_raising(self, _name, key):
        self._queue(DeletionType.Cohort_full, key, "8_1")

        # A key the producer never wrote cannot match cohort rows, so dropping it loses no deletion;
        # what matters is that one such row does not take the whole pass down.
        assert _collapse(DeletionType.Cohort_full) == [
            CohortDeleteTarget(team_id=self.team.pk, cohort_id=8, below_version=None)
        ]

    def test_stale_keys_without_a_numeric_version_carry_no_bound_and_are_skipped(self):
        self._queue(DeletionType.Cohort_stale, "8_None", "9_2")

        # An unbounded stale sweep would delete every version of cohort 8, which is what
        # Cohort_full means, not Cohort_stale.
        assert _collapse(DeletionType.Cohort_stale) == [
            CohortDeleteTarget(team_id=self.team.pk, cohort_id=9, below_version=2)
        ]

    def test_an_undrained_table_fails_the_run_instead_of_reporting_a_failed_pass(self):
        self._queue(DeletionType.Cohort_full, "5_1")

        # The job chains the person sweep on this returning, and the two must not mutate at the
        # same time. Recording the drain as a failed pass would let the person sweep start anyway.
        # The first count clears the capacity check so a mutation is enqueued; it then never drains.
        with (
            patch("posthog.models.async_deletion.delete_cohorts.sync_execute", return_value=[]),
            patch("posthog.models.async_deletion.delete_cohorts._server_now", return_value=NOW),
            patch("posthog.models.async_deletion.delete_cohorts._lowest_versions", return_value={(self.team.pk, 5): 0}),
            patch(
                "posthog.models.async_deletion.delete_cohorts._mutation_counts",
                side_effect=[(0, 0), *[(1, 1)] * 40],
            ),
            patch("posthog.models.async_deletion.delete_cohorts.time.sleep"),
            patch("posthog.models.async_deletion.delete_cohorts.time.monotonic", side_effect=range(0, 100_000, 500)),
        ):
            with pytest.raises(TimeoutError, match="unfinished mutation"):
                sweep_cohort_deletions()

    def test_a_capacity_timeout_is_a_failed_pass_because_nothing_was_enqueued(self):
        self._queue(DeletionType.Cohort_full, "7_1")

        # Another mutation holding the table means this sweep started nothing, so there is no
        # overlap to prevent and the run continues to the person sweep.
        with (
            patch("posthog.models.async_deletion.delete_cohorts.sync_execute", return_value=[]),
            patch("posthog.models.async_deletion.delete_cohorts._server_now", return_value=NOW),
            patch("posthog.models.async_deletion.delete_cohorts._lowest_versions", return_value={(self.team.pk, 7): 0}),
            # Mirrors the real filter: mutations older than this run are invisible to the drain.
            patch(
                "posthog.models.async_deletion.delete_cohorts._mutation_counts",
                side_effect=lambda since=None: (0, 0) if since else (9, 9),
            ),
            patch("posthog.models.async_deletion.delete_cohorts.time.sleep"),
            patch("posthog.models.async_deletion.delete_cohorts.time.monotonic", side_effect=range(0, 100_000, 500)),
        ):
            assert sweep_cohort_deletions() == ["run:Cohort_full"]

    def test_the_drain_waits_for_enqueued_mutations_to_become_visible(self):
        self._queue(DeletionType.Cohort_full, "6_1")

        # A mutation entry replicates through Keeper, so right after the ALTER the queried host can
        # report nothing unfinished simply because it does not know about it yet. Treating that gap
        # as a finished drain releases the person sweep on top of a running mutation.
        counts = [(0, 0), (0, 0), (1, 1), (1, 0)]
        with (
            patch("posthog.models.async_deletion.delete_cohorts.sync_execute", return_value=[]),
            patch("posthog.models.async_deletion.delete_cohorts._server_now", return_value=NOW),
            patch("posthog.models.async_deletion.delete_cohorts._lowest_versions", return_value={(self.team.pk, 6): 0}),
            patch(
                "posthog.models.async_deletion.delete_cohorts._mutation_counts", side_effect=counts
            ) as mutation_counts,
            patch("posthog.models.async_deletion.delete_cohorts.time.sleep"),
            patch("posthog.models.async_deletion.delete_cohorts.time.monotonic", side_effect=range(100)),
        ):
            assert sweep_cohort_deletions() == []

        assert mutation_counts.call_count == len(counts)
