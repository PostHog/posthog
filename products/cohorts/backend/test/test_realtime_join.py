from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.models.realtime_request import (
    UNFINISHED_REQUEST_STATES,
    RealtimeCohortRequest,
    RealtimeCohortRequestKind,
    RealtimeCohortRequestState,
)
from products.cohorts.backend.realtime_join import JoinFacts, RealtimeCohortsJoinState, decide_join_state

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def _request(
    state: RealtimeCohortRequestState, *, age: timedelta, started_age: timedelta | None = None
) -> RealtimeCohortRequest:
    at = NOW - age
    return RealtimeCohortRequest(
        kind=RealtimeCohortRequestKind.ENABLE,
        state=state,
        created_at=at,
        started_at=None if state == RealtimeCohortRequestState.QUEUED else NOW - (started_age or age),
        finished_at=None if state in UNFINISHED_REQUEST_STATES else at,
    )


class TestDecideJoinState(SimpleTestCase):
    @parameterized.expand(
        [
            ("serving_for_a_snapshot_lifetime", timedelta(seconds=30), None, False, False, "serving"),
            ("serving_before_every_process_sees_it", timedelta(seconds=10), None, True, False, "setting_up"),
            ("serving_with_the_join_closed", timedelta(hours=1), None, False, True, "serving"),
            (
                "queued_with_the_join_closed",
                None,
                _request(RealtimeCohortRequestState.QUEUED, age=timedelta(minutes=5)),
                False,
                False,
                "setting_up",
            ),
            (
                "running_with_the_join_closed",
                None,
                _request(RealtimeCohortRequestState.RUNNING, age=timedelta(minutes=5)),
                False,
                False,
                "setting_up",
            ),
            (
                "running_after_a_long_queue",
                None,
                _request(RealtimeCohortRequestState.RUNNING, age=timedelta(hours=3), started_age=timedelta(minutes=5)),
                True,
                False,
                "setting_up",
            ),
            (
                "stale_running_request",
                None,
                _request(RealtimeCohortRequestState.RUNNING, age=timedelta(hours=3)),
                True,
                False,
                "available",
            ),
            ("closed", None, None, False, False, "not_open"),
            ("closed_and_refused_now", None, None, False, True, "not_open"),
            ("refused_now", None, None, True, True, "refused"),
            (
                "refused_6_days_ago",
                None,
                _request(RealtimeCohortRequestState.REFUSED, age=timedelta(days=6)),
                True,
                False,
                "refused",
            ),
            (
                "refused_8_days_ago",
                None,
                _request(RealtimeCohortRequestState.REFUSED, age=timedelta(days=8)),
                True,
                False,
                "available",
            ),
            (
                "failed_30_minutes_ago",
                None,
                _request(RealtimeCohortRequestState.FAILED, age=timedelta(minutes=30)),
                True,
                False,
                "failed",
            ),
            (
                "failed_2_hours_ago",
                None,
                _request(RealtimeCohortRequestState.FAILED, age=timedelta(hours=2)),
                True,
                False,
                "available",
            ),
            ("never_asked", None, None, True, False, "available"),
        ]
    )
    def test_decides_the_join_state(
        self,
        _name: str,
        serving_for: timedelta | None,
        last_request: RealtimeCohortRequest | None,
        join_open: bool,
        enablement_refused: bool,
        expected: str,
    ) -> None:
        facts = JoinFacts(
            serving_since=None if serving_for is None else NOW - serving_for,
            join_open=join_open,
            enablement_refused=enablement_refused,
            last_request=last_request,
        )

        assert decide_join_state(facts, NOW) == RealtimeCohortsJoinState(expected)
