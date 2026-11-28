import pytest

from django.test import override_settings

from products.batch_exports.backend.events_table import batch_exports_read_new_events_table


@pytest.mark.parametrize(
    "export_opted_in,team_ids,excluded_team_ids,rollout_percentage,expected",
    [
        (False, [], [], 0, False),
        (False, [], [], 100, True),
        (False, ["42"], [], 0, True),
        (False, ["42"], ["42"], 100, False),
        (False, [], ["42"], 100, False),
        (True, [], ["42"], 0, True),
    ],
    ids=[
        "off",
        "full-rollout",
        "listed-team",
        "excluded-beats-listed",
        "excluded-beats-rollout",
        "export-opt-in-beats-excluded",
    ],
)
def test_batch_exports_read_new_events_table(
    export_opted_in: bool, team_ids: list[str], excluded_team_ids: list[str], rollout_percentage: int, expected: bool
) -> None:
    with override_settings(
        BATCH_EXPORTS_NEW_EVENTS_TABLE_TEAM_IDS=team_ids,
        BATCH_EXPORTS_NEW_EVENTS_TABLE_EXCLUDED_TEAM_IDS=excluded_team_ids,
        BATCH_EXPORTS_NEW_EVENTS_TABLE_ROLLOUT_PERCENTAGE=rollout_percentage,
    ):
        assert batch_exports_read_new_events_table(42, export_opted_in=export_opted_in) is expected


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
