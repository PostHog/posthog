from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

import pytest

import dagster
from clickhouse_driver import Client
from parameterized import parameterized

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.flag_evaluations_parity import (
    FlagEvaluationsParityConfig,
    ParityResults,
    TeamParity,
    measure_flag_evaluations_parity,
    parity_alert_lines,
)
from posthog.dags.tests.conftest import insert_flag_evaluations


def _results(checked: list[TeamParity], teams_truncated: int = 0) -> ParityResults:
    return ParityResults(
        day=datetime.now(tz=UTC).date(),
        checked=checked,
        teams_enabled=len(checked) + teams_truncated,
        teams_truncated=teams_truncated,
    )


class TestParityAlertLines:
    @parameterized.expand(
        [
            ("clean", [TeamParity(1, 0, 0, 100)], 0),
            # The permanent duplicate surplus must never alert on its own, or the job fires
            # every day for every team and stops being read.
            ("excess_only", [TeamParity(1, 0, 250, 100)], 0),
        ]
    )
    def test_stays_quiet(self, _name: str, checked: list[TeamParity], truncated: int) -> None:
        assert parity_alert_lines(_results(checked, truncated)) is None

    @parameterized.expand(
        [
            ("deficit", [TeamParity(1, 3, 0, 100)], 0, "3 rows in events"),
            # A capped run must not read as full coverage.
            ("truncated_without_deficit", [TeamParity(1, 0, 0, 100)], 5, "5 enabled teams were not checked"),
        ]
    )
    def test_alerts(self, _name: str, checked: list[TeamParity], truncated: int, expected: str) -> None:
        lines = parity_alert_lines(_results(checked, truncated))
        assert lines is not None
        assert any(expected in line for line in lines)

    def test_summary_counts_queried_teams_not_only_teams_with_rows(self) -> None:
        # Ten teams were queried but only one had rows on the day. The summary must report the
        # queried count, not len(checked), or it understates coverage and contradicts the
        # truncation line.
        results = ParityResults(
            day=datetime.now(tz=UTC).date(),
            checked=[TeamParity(1, 5, 0, 0)],
            teams_enabled=10,
            teams_truncated=0,
        )
        lines = parity_alert_lines(results)
        assert lines is not None
        assert any("Checked 10 of 10 enabled teams (1 had rows on the day)" in line for line in lines)


@pytest.mark.django_db
def test_measure_attributes_deficit_and_excess_to_the_right_team(cluster: ClickhouseCluster) -> None:
    day = (datetime.now(tz=UTC) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    earlier = day - timedelta(days=1)
    matched, also_matched, events_only, fork_only = UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4)
    person = UUID(int=99)
    clean_team, deficit_team, excess_team, activation_team = 8001, 8002, 8003, 8004

    def insert_events(client: Client) -> None:
        flag_props = '{"$feature_flag": "my-flag"}'
        client.execute(
            """INSERT INTO writable_events (team_id, event, distinct_id, person_id, uuid, timestamp, properties)
            VALUES
            """,
            [
                (clean_team, "$feature_flag_called", "d", person, matched, day, flag_props),
                (deficit_team, "$feature_flag_called", "d", person, also_matched, day, flag_props),
                (deficit_team, "$feature_flag_called", "d", person, events_only, day, flag_props),
                # The fork only writes for a non-empty string $feature_flag, so a
                # $feature_flag_called event without one has no flag_evaluations row by
                # design and must not read as a deficit. Missing, empty, and non-string
                # all match the fork's typeof-string check.
                (deficit_team, "$feature_flag_called", "d", person, UUID(int=6), day, "{}"),
                (deficit_team, "$feature_flag_called", "d", person, UUID(int=7), day, '{"$feature_flag": ""}'),
                (deficit_team, "$feature_flag_called", "d", person, UUID(int=8), day, '{"$feature_flag": 5}'),
                # A different event with a uuid the fork never sees must not read as a deficit.
                (excess_team, "$pageview", "d", person, UUID(int=5), day, ""),
                # activation_team is switched on during the checked day: this earlier event
                # has no fork row, so checking the team would read as a deficit. The op must
                # skip the team instead.
                (activation_team, "$feature_flag_called", "d", person, UUID(int=9), day, flag_props),
            ],
        )

    cluster.any_host(insert_events).result()
    cluster.any_host(
        partial(
            insert_flag_evaluations,
            [
                # A row before the checked day marks each team as one the fork was already
                # writing for, so it stays in the enabled set and is compared on the day.
                (clean_team, "d", person, UUID(int=10), earlier),
                (deficit_team, "d", person, UUID(int=11), earlier),
                (excess_team, "d", person, UUID(int=12), earlier),
                (clean_team, "d", person, matched, day),
                # Enabled, so the op checks it, but one of its two events never arrived.
                (deficit_team, "d", person, also_matched, day),
                # Two rows for one uuid: a duplicate is excess, and excess is not a deficit.
                (excess_team, "d", person, fork_only, day),
                (excess_team, "d", person, fork_only, day),
                # activation_team's first-ever row is on the checked day, so it was switched
                # on that day and must be skipped rather than compared.
                (activation_team, "d", person, UUID(int=13), day),
            ],
        )
    ).result()

    # Two teams per query and three teams compared, so the batching loop runs more than once.
    config = FlagEvaluationsParityConfig(teams_per_query=2)
    results = measure_flag_evaluations_parity(dagster.build_op_context(), config, cluster)

    by_team = {team.team_id: team for team in results.checked}
    assert by_team[clean_team] == TeamParity(clean_team, only_in_events=0, only_in_flag_evaluations=0, in_both=1)
    assert by_team[deficit_team] == TeamParity(deficit_team, only_in_events=1, only_in_flag_evaluations=0, in_both=1)
    assert by_team[excess_team] == TeamParity(excess_team, only_in_events=0, only_in_flag_evaluations=1, in_both=0)
    # Switched on during the checked day, so it is skipped rather than reported as a deficit.
    assert activation_team not in by_team
