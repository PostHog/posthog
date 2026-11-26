import sys
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.conf import settings

from temporalio.testing import ActivityEnvironment

from posthog.quota_spine_comparison import (
    COMPARISON_FLAG,
    EMPTY,
    MISMATCH_EVENT,
    STATE_KEY,
    STATE_TTL,
    Key,
    QuotaLevel,
    compare,
    compare_with_spine,
    labels,
    quota_levels,
)
from posthog.redis import get_client
from posthog.temporal.quota_limiting.run_quota_limiting import (
    QuotaLimitingResult,
    RunQuotaLimitingAllOrgsInputs,
    run_quota_limiting_all_orgs,
)

from ee.billing.billing_types import BillingLimit, BillingLimits
from ee.billing.quota_limiting import QuotaLimitingRunResult, QuotaResource

T0 = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
ORG, RESOURCE = "org", "events"
KEY = (ORG, RESOURCE)


def after(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def row(**fields: Any) -> BillingLimit:
    return cast(
        BillingLimit,
        {
            "organization_id": ORG,
            "resource": RESOURCE,
            "usage": "4",
            "limit": "10",
            "over_limit": False,
            "enforced": False,
            "grace_expiry": None,
            "never_drop_data": False,
            **fields,
        },
    )


RECENTLY = after(-5)


def spine(*rows: BillingLimit, usage_through: datetime = RECENTLY) -> BillingLimits:
    return {"usage_through": usage_through.isoformat().replace("+00:00", "Z"), "limits": list(rows)}


LIMITING_OFF: BillingLimits = {"usage_through": None, "limits": []}
UNDER = row()
IN_GRACE = row(usage="20", over_limit=True, grace_expiry="2026-11-27T10:05:00Z")
ENFORCED = row(usage="20", over_limit=True, enforced=True)
EXEMPT = row(usage="20", over_limit=True, enforced=True, never_drop_data=True)
CREDITS = QuotaResource.AI_CREDITS.value
ON_CREDITS = (ORG, CREDITS)
EXEMPT_ON_CREDITS = row(resource=CREDITS, usage="20", over_limit=True, enforced=True, never_drop_data=True)
LIMITED: dict[Key, QuotaLevel] = {KEY: "limited"}


@pytest.mark.parametrize(
    "quota,rows,label",
    [
        ({}, [], None),
        ({}, [UNDER], None),
        ({}, [EXEMPT], None),
        ({KEY: "suspended"}, [IN_GRACE], None),
        ({KEY: "limited"}, [ENFORCED], None),
        ({KEY: "limited"}, [], "no_spine_limit"),
        ({KEY: "suspended"}, [], "no_spine_limit"),
        ({ON_CREDITS: "limited"}, [EXEMPT_ON_CREDITS], "exempt"),
        ({ON_CREDITS: "suspended"}, [EXEMPT_ON_CREDITS], "exempt"),
        ({KEY: "limited"}, [EXEMPT], "unexplained"),
        ({KEY: "limited"}, [row(usage="10", never_drop_data=True)], "unexplained"),
        ({KEY: "limited"}, [IN_GRACE], "grace"),
        ({KEY: "suspended"}, [ENFORCED], "grace"),
        ({}, [ENFORCED], "unexplained"),
        ({}, [IN_GRACE], "unexplained"),
        ({KEY: "limited"}, [UNDER], "unexplained"),
        ({KEY: "suspended"}, [UNDER], "unexplained"),
        ({KEY: "limited"}, [row(usage="9.89")], "unexplained"),
        ({KEY: "limited"}, [row(usage="9.90")], "near_limit"),
        ({}, [row(usage="10.10", over_limit=True, enforced=True)], "near_limit"),
        ({}, [row(usage="10.11", over_limit=True, enforced=True)], "unexplained"),
    ],
)
def test_labels_each_pair_of_levels(quota: dict[Key, QuotaLevel], rows: list[BillingLimit], label: str | None) -> None:
    state, _ = compare(quota, spine(*rows), EMPTY, T0)

    assert labels(state) == ({label: 1} if label else {})


def test_a_mismatch_is_confirmed_once_a_report_started_after_it_was_first_seen() -> None:
    seen, first = compare(LIMITED, spine(usage_through=after(-5)), EMPTY, T0)
    waiting, second = compare(LIMITED, spine(usage_through=after(10)), seen, after(15))
    confirmed, third = compare(LIMITED, spine(usage_through=after(25)), waiting, after(30))
    _, fourth = compare(LIMITED, spine(usage_through=after(40)), confirmed, after(45))

    assert first == second == fourth == []
    assert third == [
        {
            "organization_id": ORG,
            "resource": RESOURCE,
            "label": "no_spine_limit",
            "quota_level": "limited",
            "spine_level": "absent",
            "usage": None,
            "limit": None,
            "grace_expiry": None,
            "since": T0.isoformat(),
        }
    ]


def test_a_report_that_started_as_the_mismatch_was_first_seen_does_not_confirm_it() -> None:
    seen, _ = compare(LIMITED, spine(usage_through=after(-5)), EMPTY, T0)
    waiting, _ = compare(LIMITED, spine(usage_through=T0), seen, after(15))
    _, confirmed = compare(LIMITED, spine(usage_through=after(20)), waiting, after(30))

    assert confirmed == []


def test_a_confirmed_mismatch_carries_what_the_spine_holds() -> None:
    state = EMPTY
    for minutes in (0, 15, 30):
        state, confirmed = compare(LIMITED, spine(IN_GRACE, usage_through=after(minutes - 5)), state, after(minutes))

    assert [(m["label"], m["spine_level"], m["usage"], m["limit"], m["grace_expiry"]) for m in confirmed] == [
        ("grace", "over", "20", "10", "2026-11-27T10:05:00Z")
    ]


def test_nothing_is_confirmed_while_reports_stall() -> None:
    state = EMPTY
    for minutes in (0, 15, 30, 45):
        state, confirmed = compare(LIMITED, spine(usage_through=after(-5)), state, after(minutes))

        assert confirmed == []


def test_a_backlog_is_confirmed_over_several_runs() -> None:
    quota: dict[Key, QuotaLevel] = {(organization_id, RESOURCE): "limited" for organization_id in ("a", "b", "c")}
    state, batches = EMPTY, []
    with patch("posthog.quota_spine_comparison.CONFIRMED_PER_RUN", 2):
        for minutes in (0, 15, 30, 45, 60):
            state, confirmed = compare(quota, spine(usage_through=after(minutes - 5)), state, after(minutes))
            batches.append([mismatch["organization_id"] for mismatch in confirmed])

    assert batches == [[], [], ["a", "b"], ["c"], []]


def test_a_mismatch_that_goes_away_starts_over_when_it_returns() -> None:
    seen, _ = compare(LIMITED, spine(), EMPTY, T0)
    gone, _ = compare({}, spine(), seen, after(15))
    back, _ = compare(LIMITED, spine(), gone, after(30))

    assert gone["mismatches"] == {}
    assert list(back["mismatches"].values()) == [{"since": after(30).isoformat(), "confirmed": False}]


def test_a_change_of_label_starts_over() -> None:
    seen, _ = compare(LIMITED, spine(IN_GRACE), EMPTY, T0)
    changed, _ = compare(LIMITED, spine(UNDER), seen, after(15))

    assert labels(changed) == {"unexplained": 1}
    assert list(changed["mismatches"].values()) == [{"since": after(15).isoformat(), "confirmed": False}]


def test_a_change_of_levels_starts_over_even_under_the_same_label() -> None:
    state = EMPTY
    for minutes in (0, 15, 30):
        state, _ = compare({}, spine(ENFORCED, usage_through=after(minutes - 5)), state, after(minutes))
    flipped, confirmed = compare(LIMITED, spine(UNDER, usage_through=after(40)), state, after(45))

    assert labels(state) == labels(flipped) == {"unexplained": 1}
    assert confirmed == []
    assert list(flipped["mismatches"].values()) == [{"since": after(45).isoformat(), "confirmed": False}]


def test_a_limit_on_something_quota_limiting_has_no_quota_for_is_not_compared() -> None:
    without_a_quota = row(resource="not_a_quota", usage="20", over_limit=True, enforced=True)

    state, _ = compare({}, spine(without_a_quota), EMPTY, T0)

    assert state["mismatches"] == {}


def test_what_was_not_confirmed_starts_over_once_billing_has_nothing_to_compare() -> None:
    seen, _ = compare(LIMITED, spine(usage_through=after(-5)), EMPTY, T0)
    off, reported = compare(LIMITED, LIMITING_OFF, seen, after(15))
    back, _ = compare(LIMITED, spine(usage_through=after(20)), off, after(30))
    _, too_early = compare(LIMITED, spine(usage_through=after(35)), back, after(45))

    assert (off["mismatches"], reported) == ({}, [])
    assert list(back["mismatches"].values()) == [{"since": after(30).isoformat(), "confirmed": False}]
    assert too_early == []


def test_a_confirmed_mismatch_is_not_reported_again_after_billing_had_nothing_to_compare() -> None:
    state = EMPTY
    for minutes in (0, 15, 30):
        state, _ = compare(LIMITED, spine(usage_through=after(minutes - 5)), state, after(minutes))
    state, _ = compare(LIMITED, LIMITING_OFF, state, after(45))

    for minutes in (60, 75, 90):
        state, confirmed = compare(LIMITED, spine(usage_through=after(minutes - 5)), state, after(minutes))

        assert confirmed == []


def test_a_discarded_decision_is_not_a_mismatch() -> None:
    state = EMPTY
    for minutes in (0, 15, 30, 45):
        billing = spine(ENFORCED, usage_through=after(minutes - 5))
        state, confirmed = compare({}, billing, state, after(minutes), discarded={ORG})

        assert (state["mismatches"], confirmed) == ({}, [])


def test_a_discarded_decision_leaves_what_was_seen_as_it_was() -> None:
    seen, _ = compare(LIMITED, spine(usage_through=after(-5)), EMPTY, T0)
    discarded, during = compare({}, spine(usage_through=after(10)), seen, after(15), discarded={ORG})
    _, afterwards = compare(LIMITED, spine(usage_through=after(25)), discarded, after(30))

    assert discarded["mismatches"] == seen["mismatches"]
    assert during == []
    assert [mismatch["since"] for mismatch in afterwards] == [T0.isoformat()]


def test_a_discarded_decision_keeps_nothing_of_another_organization() -> None:
    seen, _ = compare(LIMITED, spine(), EMPTY, T0)
    gone, _ = compare({}, spine(), seen, after(15), discarded={"another"})

    assert gone["mismatches"] == {}


def test_a_confirmed_mismatch_is_not_reported_again_after_its_decision_was_discarded() -> None:
    state = EMPTY
    for minutes in (0, 15, 30):
        state, _ = compare(LIMITED, spine(usage_through=after(minutes - 5)), state, after(minutes))
    state, _ = compare({}, spine(usage_through=after(40)), state, after(45), discarded={ORG})

    for minutes in (60, 75, 90):
        state, confirmed = compare(LIMITED, spine(usage_through=after(minutes - 5)), state, after(minutes))

        assert confirmed == []


RUN = QuotaLimitingRunResult(
    quota_limited_orgs={"events": {"used": 1, "unused": 1}, "recordings": {"unused": 1}},
    quota_limiting_suspended_orgs={"events": {"graced": 1}, "recordings": {}},
    orgs_with_usage={"events": {"used", "graced"}, "recordings": set()},
    discarded_orgs=set(),
    stats={"orgs_limited": 2},
)
USED = QuotaLimitingRunResult(
    quota_limited_orgs={"events": {"used": 1}},
    quota_limiting_suspended_orgs={"events": {}},
    orgs_with_usage={"events": {"used"}},
    discarded_orgs=set(),
    stats={},
)


def test_quota_levels_leave_out_orgs_limited_on_a_resource_they_have_not_used() -> None:
    assert quota_levels(RUN) == {("used", "events"): "limited", ("graced", "events"): "suspended"}


class TestCompareWithSpine:
    @pytest.fixture(autouse=True)
    def billing(self) -> Iterator[None]:
        get_client().delete(STATE_KEY)
        with (
            patch("posthog.quota_spine_comparison.is_cloud", return_value=True),
            patch("posthog.quota_spine_comparison.get_cached_instance_license", return_value=MagicMock()),
            patch("posthog.quota_spine_comparison.BillingManager") as manager,
            patch("posthog.quota_spine_comparison.get_instance_region", return_value="EU"),
            patch("posthog.quota_spine_comparison.ph_scoped_capture", self.scoped_capture),
            patch("posthog.quota_spine_comparison.feature_enabled_or_false", return_value=True) as flag,
        ):
            self.flag = flag
            self.get_limiting = manager.return_value.get_limiting
            self.get_limiting.return_value = spine()
            self.capture = MagicMock()
            self.event_regions: list[str | None] = []
            self.delivery_error: Exception | None = None
            yield

    @contextmanager
    def scoped_capture(self, *, event_region: str | None = None, raise_on_error: bool = False) -> Iterator[MagicMock]:
        """Stands in for `ph_scoped_capture`: delivers when the block ends, and raises a failure only when asked to."""
        self.event_regions.append(event_region)
        yield self.capture
        if self.delivery_error and raise_on_error:
            raise self.delivery_error

    def test_still_asks_when_it_limits_nobody(self) -> None:
        nobody = QuotaLimitingRunResult(
            quota_limited_orgs={}, quota_limiting_suspended_orgs={}, orgs_with_usage={}, discarded_orgs=set(), stats={}
        )

        compare_with_spine(nobody)

        self.get_limiting.assert_called_once_with([])

    async def quota_run(self) -> QuotaLimitingResult:
        with patch("ee.billing.quota_limiting.update_all_orgs_billing_quotas", return_value=RUN):
            return await ActivityEnvironment().run(run_quota_limiting_all_orgs, RunQuotaLimitingAllOrgsInputs())

    @pytest.mark.asyncio
    async def test_the_quota_run_asks_billing_and_returns_its_own_result(self) -> None:
        result = await self.quota_run()

        self.get_limiting.assert_called_once_with(["graced", "used"])
        assert result.orgs_limited == 2

    @pytest.mark.asyncio
    async def test_a_billing_error_does_not_fail_the_quota_run(self) -> None:
        self.get_limiting.side_effect = Exception("billing is down")

        with patch("posthog.temporal.quota_limiting.run_quota_limiting.capture_exception") as capture_exception:
            result = await self.quota_run()

        assert result.orgs_limited == 2
        capture_exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_comparison_that_fails_to_load_does_not_skip_the_quota_run(self) -> None:
        with (
            # None in sys.modules makes the import raise.
            patch.dict(sys.modules, {"posthog.quota_spine_comparison": None}),
            patch("posthog.temporal.quota_limiting.run_quota_limiting.capture_exception") as capture_exception,
        ):
            result = await self.quota_run()

        assert result.orgs_limited == 2
        capture_exception.assert_called_once()

    def run_at(self, minutes: int) -> None:
        self.get_limiting.return_value = spine(usage_through=after(minutes - 5))
        with time_machine.travel(after(minutes), tick=False):
            compare_with_spine(USED)

    def test_captures_a_mismatch_once_when_it_is_confirmed(self) -> None:
        for minutes in (0, 15, 30, 45):
            self.run_at(minutes)

        self.capture.assert_called_once_with(
            distinct_id="used",
            event=MISMATCH_EVENT,
            properties={
                "organization_id": "used",
                "resource": "events",
                "label": "no_spine_limit",
                "quota_level": "limited",
                "spine_level": "absent",
                "usage": None,
                "limit": None,
                "grace_expiry": None,
                "since": T0.isoformat(),
            },
            groups={"instance": settings.SITE_URL, "organization": "used"},
        )

    def test_a_mismatch_whose_event_was_not_delivered_is_captured_again_on_the_next_run(self) -> None:
        self.run_at(0)
        self.run_at(15)
        self.delivery_error = Exception("the events did not arrive")
        with pytest.raises(Exception, match="the events did not arrive"):
            self.run_at(30)
        self.delivery_error = None
        self.run_at(45)

        assert self.capture.call_count == 2

    def test_an_event_says_which_region_it_is_from(self) -> None:
        self.run_at(0)

        assert self.event_regions == ["EU"]

    def test_a_discarded_decision_is_not_compared(self) -> None:
        self.get_limiting.return_value = spine(row(organization_id="discarded", usage="20", enforced=True))
        discarded = QuotaLimitingRunResult(
            quota_limited_orgs={},
            quota_limiting_suspended_orgs={},
            orgs_with_usage={},
            discarded_orgs={"discarded"},
            stats={},
        )

        compare_with_spine(discarded)

        assert json.loads(get_client().get(STATE_KEY) or "null") == {
            "usage_through": RECENTLY.isoformat().replace("+00:00", "Z"),
            "mismatches": {},
        }

    def test_keeps_its_state_for_a_week(self) -> None:
        with time_machine.travel(T0, tick=False):
            compare_with_spine(USED)

            assert get_client().ttl(STATE_KEY) == STATE_TTL.total_seconds()

    @pytest.mark.parametrize("missing", ["is_cloud", "get_cached_instance_license"])
    def test_does_nothing_outside_cloud_or_without_a_license(self, missing: str) -> None:
        with patch(f"posthog.quota_spine_comparison.{missing}", return_value=None):
            compare_with_spine(RUN)

        self.get_limiting.assert_not_called()

    def test_does_nothing_while_its_flag_is_off(self) -> None:
        self.flag.return_value = False

        compare_with_spine(USED)

        self.get_limiting.assert_not_called()
        assert get_client().get(STATE_KEY) is None

    def test_reads_its_flag_for_this_region_from_the_flags_the_worker_holds(self) -> None:
        compare_with_spine(RUN)

        self.flag.assert_called_once_with(
            COMPARISON_FLAG,
            "internal_billing_events",
            person_properties={"region": "EU"},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
