from types import SimpleNamespace

import pytest

import dagster
from parameterized import parameterized

from posthog.dags.personhog_shadow_lane import (
    ShadowLaneStartConfig,
    _reset_shadow_state,
    require_shadow_dsn,
    wait_for_quiescence,
)


class TestRequireShadowDsn:
    @parameterized.expand(
        [
            ("postgres://user:pass@persons-shadow.cluster-abc.us-east-1.rds.amazonaws.com:5432/posthog",),
            ("postgres://user@localhost:5432/persons_shadow_test",),
        ]
    )
    def test_accepts_shadow_targets(self, url: str) -> None:
        require_shadow_dsn(url)

    @parameterized.expand(
        [
            (
                "postgres://user:pass@posthog-cloud-persons-prod-us-east-1.cluster-abc.us-east-1.rds.amazonaws.com:5432/posthog",
            ),
            ("postgres://user@localhost:5432/posthog_persons",),
            ("postgres://user:shadow@localhost:5432/posthog_persons",),
            # libpq lets query parameters and multi-host authorities point the
            # connection somewhere other than the URL's hostname.
            ("postgres://user@persons-shadow.example:5432/posthog?hostaddr=10.0.0.1",),
            ("postgres://user@persons-shadow.example:5432/posthog?host=prod.example",),
            ("postgres://user@persons-shadow.example:5432/posthog?dbname=production",),
            ("postgres://user@persons-shadow.example:5432/posthog?service=prod",),
            ("postgres://user@persons-shadow.example,prod.example:5432/posthog",),
            # A libpq key/value DSN has no URL authority for the guard to check.
            ("host=prod.example dbname=posthog user=dagster_shadow",),
        ]
    )
    def test_rejects_non_shadow_targets(self, url: str) -> None:
        with pytest.raises(dagster.Failure):
            require_shadow_dsn(url)


class TestWaitForQuiescence:
    @parameterized.expand(
        [
            ("flat_counter", [5, 5, 5, 5], 3, 4),
            ("moving_then_flat", [5, 6, 6, 7, 7, 7], 2, 6),
        ]
    )
    def test_returns_once_counter_is_stable(
        self, _name: str, readings: list[int], stable_checks: int, expected_polls: int
    ) -> None:
        values = iter(readings)
        polls = wait_for_quiescence(
            lambda: next(values),
            poll_seconds=0,
            stable_checks=stable_checks,
            timeout_seconds=60,
            sleep=lambda _seconds: None,
        )
        assert polls == expected_polls

    def test_raises_when_counter_never_settles(self) -> None:
        counter = iter(range(1000))
        with pytest.raises(TimeoutError):
            wait_for_quiescence(
                lambda: next(counter),
                poll_seconds=0,
                stable_checks=2,
                timeout_seconds=0,
                sleep=lambda _seconds: None,
            )


class _FakeAppsApi:
    def __init__(self, desired_replicas: int) -> None:
        self.desired_replicas = desired_replicas

    def read_namespaced_deployment(self, name: str, namespace: str) -> SimpleNamespace:
        return SimpleNamespace(spec=SimpleNamespace(replicas=self.desired_replicas))


def test_reset_refuses_while_lane_wants_pods() -> None:
    context = dagster.build_op_context()
    with pytest.raises(dagster.Failure, match="stop-and-compare"):
        _reset_shadow_state(context, ShadowLaneStartConfig(reset_state=True), _FakeAppsApi(desired_replicas=2))
