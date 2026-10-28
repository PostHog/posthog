import pytest

from migration_replay_plan import moved_master_migration

MASTER_PLAN = ["actions.0001 a1", "posthog.0001 p1", "workflows.0001 w1"]


@pytest.mark.parametrize(
    "plan, needs_replay",
    [
        (MASTER_PLAN, False),
        (["actions.0001 a1", "actions.0002 a2", "posthog.0001 p1", "workflows.0001 w1"], False),
        (["actions.0001 a1", "posthog.0001 p1", "workflows.0001 w1", "workflows.0002 w2"], False),
        (["actions.0001 a1", "workflows.0001 w1", "actions.0002 a2", "posthog.0001 p1"], True),
        (["actions.0001 a1", "posthog.0001 edited", "workflows.0001 w1"], True),
        (["actions.0001 a1", "posthog.0001 p1"], True),
    ],
    ids=["unchanged", "new-mid-plan", "new-at-end", "reordered", "edited", "deleted"],
)
def test_moved_master_migration(plan: list[str], needs_replay: bool) -> None:
    assert (moved_master_migration(plan, MASTER_PLAN) is not None) == needs_replay
