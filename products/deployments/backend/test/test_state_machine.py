"""Pure-unit tests for the deployment status state machine.

Lives outside the DB layer — exercises domain/status.py directly. The
transition rules are the most safety-critical thing in this product
(the internal endpoint is the only place we mutate `Deployment.status`)
so we want exhaustive coverage with no test infra in the way.
"""

from __future__ import annotations

from itertools import product

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.deployments.backend.domain.status import (
    NON_TERMINAL_STATUSES,
    TERMINAL_STATUSES,
    VALID_TRANSITIONS,
    InvalidStatusTransition,
    Status,
    assert_valid,
    is_idempotent_noop,
)

_ALL_STATUSES = tuple(Status)


class TestStateMachine(BaseTest):
    @parameterized.expand([(c.value, t.value) for (c, t) in VALID_TRANSITIONS])
    def test_every_valid_transition_passes_assert_valid(self, current: str, target: str) -> None:
        # No exception raised = pass.
        assert_valid(Status(current), Status(target))

    @parameterized.expand(
        [
            (c.value, t.value)
            for (c, t) in product(_ALL_STATUSES, _ALL_STATUSES)
            if (c, t) not in VALID_TRANSITIONS and not (c == t and c in TERMINAL_STATUSES)
        ]
    )
    def test_invalid_transitions_raise(self, current: str, target: str) -> None:
        with self.assertRaises(InvalidStatusTransition):
            assert_valid(Status(current), Status(target))

    @parameterized.expand(
        [
            (Status.READY.value,),
            (Status.ERROR.value,),
            (Status.CANCELLED.value,),
        ]
    )
    def test_is_idempotent_noop_for_matching_terminal(self, status: str) -> None:
        self.assertTrue(is_idempotent_noop(Status(status), Status(status)))

    @parameterized.expand(
        [
            (Status.QUEUED.value,),
            (Status.INITIALIZING.value,),
            (Status.BUILDING.value,),
        ]
    )
    def test_is_idempotent_noop_false_for_non_terminal_self_loop(self, status: str) -> None:
        # `queued → queued` is NOT an idempotent no-op — the worker should
        # never claim it's still queued. Detect that as a programmer error.
        self.assertFalse(is_idempotent_noop(Status(status), Status(status)))

    def test_is_idempotent_noop_false_when_statuses_differ(self) -> None:
        self.assertFalse(is_idempotent_noop(Status.READY, Status.ERROR))
        self.assertFalse(is_idempotent_noop(Status.BUILDING, Status.READY))

    def test_non_terminal_and_terminal_partition_all_statuses(self) -> None:
        # Together they should cover the enum exactly and not overlap.
        self.assertSetEqual(
            set(NON_TERMINAL_STATUSES) | set(TERMINAL_STATUSES),
            set(_ALL_STATUSES),
        )
        self.assertSetEqual(
            set(NON_TERMINAL_STATUSES) & set(TERMINAL_STATUSES),
            set(),
        )

    def test_no_transition_from_terminal_state_is_valid(self) -> None:
        for terminal in TERMINAL_STATUSES:
            for target in _ALL_STATUSES:
                if terminal == target and terminal in TERMINAL_STATUSES:
                    # idempotent_noop is handled by is_idempotent_noop, not VALID_TRANSITIONS
                    continue
                self.assertNotIn(
                    (terminal, target),
                    VALID_TRANSITIONS,
                    f"{terminal} → {target} should not be a valid transition",
                )
