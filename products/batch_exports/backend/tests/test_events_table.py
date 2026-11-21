import pytest

from django.test import override_settings

from products.batch_exports.backend.events_table import batch_exports_read_new_events_table


@pytest.mark.parametrize(
    "team_ids,excluded_team_ids,rollout_percentage,expected",
    [
        ([], [], 0, False),
        ([], [], 100, True),
        (["42"], [], 0, True),
        (["42"], ["42"], 100, False),
        ([], ["42"], 100, False),
    ],
    ids=["off", "full-rollout", "listed-team", "excluded-beats-listed", "excluded-beats-rollout"],
)
def test_batch_exports_read_new_events_table(
    team_ids: list[str], excluded_team_ids: list[str], rollout_percentage: int, expected: bool
) -> None:
    with override_settings(
        BATCH_EXPORTS_NEW_EVENTS_TABLE_TEAM_IDS=team_ids,
        BATCH_EXPORTS_NEW_EVENTS_TABLE_EXCLUDED_TEAM_IDS=excluded_team_ids,
        BATCH_EXPORTS_NEW_EVENTS_TABLE_ROLLOUT_PERCENTAGE=rollout_percentage,
    ):
        assert batch_exports_read_new_events_table(42) is expected


def test_raising_the_rollout_percentage_keeps_the_teams_already_moved() -> None:
    def get_moved_teams(percentage: int) -> set[int]:
        with override_settings(
            BATCH_EXPORTS_NEW_EVENTS_TABLE_TEAM_IDS=[],
            BATCH_EXPORTS_NEW_EVENTS_TABLE_EXCLUDED_TEAM_IDS=[],
            BATCH_EXPORTS_NEW_EVENTS_TABLE_ROLLOUT_PERCENTAGE=percentage,
        ):
            return {team_id for team_id in range(1, 1001) if batch_exports_read_new_events_table(team_id)}

    ten_percent, fifty_percent = get_moved_teams(10), get_moved_teams(50)

    assert ten_percent < fifty_percent
    assert 50 < len(ten_percent) < 150
