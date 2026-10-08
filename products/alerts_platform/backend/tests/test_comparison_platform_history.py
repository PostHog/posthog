from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.comparison.platform_history import (
    UnregisteredSource,
    read_platform_checks,
    teams_with_configurations,
)
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.logic.platform_alert_events import PlatformAlertEventRow, insert_events
from products.alerts_platform.backend.models import PlatformAlertConfiguration
from products.alerts_platform.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

OCCURRED_AT = datetime(2026, 9, 30, 12, tzinfo=UTC)
WINDOW = (OCCURRED_AT - timedelta(hours=1), OCCURRED_AT + timedelta(hours=1))


def _key(window_end: str) -> str:
    return f"slot:{OCCURRED_AT.isoformat()}|window:{window_end}"


class TestReadPlatformChecks(ClickhouseTestMixin, APIBaseTest):
    def _configuration(self, **overrides) -> PlatformAlertConfiguration:
        with team_scope(self.team.id):
            return PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_config={},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=5,
                **{"source_kind": PlatformAlertConfiguration.SourceKind.LOGS, **overrides},
            )

    def _row(
        self, configuration: PlatformAlertConfiguration, *, evaluation_key: str, **overrides
    ) -> PlatformAlertEventRow:
        return PlatformAlertEventRow(
            team_id=self.team.id,
            configuration_id=configuration.id,
            alert_id=overrides.pop("alert_id", uuid4()),
            grouping_key="",
            evaluation_key=evaluation_key,
            kind="firing",
            alert_name=configuration.name,
            previous_state="not_firing",
            state="firing",
            episode_started_at=OCCURRED_AT,
            value=47.0,
            labels={},
            condition_snapshot={},
            source_config_snapshot={},
            query_duration_ms=None,
            error_message=None,
            consecutive_failures=0,
            muted_notification="",
            occurred_at=OCCURRED_AT,
            **overrides,
        )

    def _record(self, configuration: PlatformAlertConfiguration, *, evaluation_key: str, **overrides) -> None:
        insert_events(self.team.id, [self._row(configuration, evaluation_key=evaluation_key, **overrides)])

    def _stored(self, configuration: PlatformAlertConfiguration) -> int:
        # Scoped to one configuration: ClickHouse is not rolled back, so a count over the team
        # sees rows other tests and earlier runs left.
        return sync_execute(
            f"SELECT count() FROM {PLATFORM_ALERT_EVENTS_TABLE} "
            "WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s",
            {"team_id": self.team.id, "configuration_id": configuration.id},
            team_id=self.team.id,
        )[0][0]

    def _read(self) -> list:
        since, until = WINDOW
        return list(read_platform_checks(team_id=self.team.id, source=SourceKind.LOGS, since=since, until=until))

    def test_a_check_carries_the_legacy_id_its_configuration_holds(self) -> None:
        legacy_id = uuid4()
        configuration = self._configuration(legacy_configuration_id=legacy_id)
        self._record(configuration, evaluation_key=_key("2026-09-30T11:59:00+00:00"))

        checks = self._read()

        assert len(checks) == 1
        assert checks[0].legacy_configuration_id == legacy_id
        assert checks[0].configuration_id == configuration.id
        assert checks[0].state == "firing"
        assert checks[0].previous_state == "not_firing"
        assert checks[0].kind == "firing"

    def test_a_pair_recorded_twice_reads_as_one_check(self) -> None:
        configuration = self._configuration(legacy_configuration_id=uuid4())
        alert_id = uuid4()
        retried = self._row(configuration, evaluation_key=_key("2026-09-30T11:59:00+00:00"), alert_id=alert_id)
        insert_events(self.team.id, [retried])
        # The second batch carries another key so it takes a different insert token and lands.
        # An identical batch is dropped by the engine, leaving no duplicate to collapse.
        insert_events(
            self.team.id,
            [retried, self._row(configuration, evaluation_key=_key("2026-09-30T12:04:00+00:00"))],
        )
        assert self._stored(configuration) == 3

        checks = self._read()

        assert len(checks) == 2
        assert len({check.evaluation_key for check in checks}) == 2

    def test_a_source_the_configuration_model_does_not_accept_is_an_error(self) -> None:
        # Without this an unregistered source reads as one that made no checks, and whoever runs
        # the first insight comparison concludes the parallel run is quiet.
        since, until = WINDOW

        with pytest.raises(UnregisteredSource):
            read_platform_checks(team_id=self.team.id, source=SourceKind.INSIGHT, since=since, until=until)

    def test_only_teams_holding_a_configuration_for_the_source_are_worth_sweeping(self) -> None:
        # A sweep over every team pays a Postgres round trip each to learn most have nothing.
        self._configuration(legacy_configuration_id=uuid4())
        self._configuration(source_kind="insight", legacy_configuration_id=uuid4())

        assert teams_with_configurations(SourceKind.LOGS) == [self.team.id]

    def test_another_source_is_not_in_a_logs_comparison(self) -> None:
        self._record(
            self._configuration(source_kind="insight", legacy_configuration_id=uuid4()),
            evaluation_key="run:2026-09-30T11:59:00+00:00",
        )

        assert self._read() == []
