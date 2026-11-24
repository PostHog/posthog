import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import jwt
from temporalio.testing import ActivityEnvironment

from posthog.quota_spine_comparison import (
    EMPTY,
    MISMATCH_EVENT,
    STATE_KEY,
    Key,
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

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import BillingLimit, BillingLimits
from ee.billing.quota_limiting import QuotaLimitingRunResult
from ee.models.license import License

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
LIMITED: dict[Key, str] = {KEY: "limited"}


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
        ({KEY: "limited"}, [EXEMPT], "exempt"),
        ({KEY: "suspended"}, [EXEMPT], "exempt"),
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
def test_labels_each_pair_of_levels(quota: dict[Key, str], rows: list[BillingLimit], label: str | None) -> None:
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


RUN = QuotaLimitingRunResult(
    quota_limited_orgs={"events": {"used": 1, "unused": 1}, "recordings": {"unused": 1}},
    quota_limiting_suspended_orgs={"events": {"graced": 1}, "recordings": {}},
    used_quota_orgs={"events": {"used", "graced"}, "recordings": set()},
    stats={"orgs_limited": 2},
)
USED = QuotaLimitingRunResult(
    quota_limited_orgs={"events": {"used": 1}},
    quota_limiting_suspended_orgs={"events": {}},
    used_quota_orgs={"events": {"used"}},
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
            patch("posthog.quota_spine_comparison.posthoganalytics.capture") as capture,
        ):
            self.get_limiting = manager.return_value.get_limiting
            self.get_limiting.return_value = spine()
            self.capture = capture
            yield

    def test_still_asks_when_it_limits_nobody(self) -> None:
        nobody = QuotaLimitingRunResult(
            quota_limited_orgs={}, quota_limiting_suspended_orgs={}, used_quota_orgs={}, stats={}
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

        self.capture.assert_called_once()
        captured = self.capture.call_args.kwargs
        assert (captured["event"], captured["distinct_id"]) == (MISMATCH_EVENT, "used")
        assert captured["groups"]["organization"] == "used"
        assert captured["properties"]["label"] == "no_spine_limit"
        assert captured["properties"]["since"] == T0.isoformat()

    def test_captures_a_confirmed_mismatch_again_when_capturing_it_failed(self) -> None:
        self.run_at(0)
        self.run_at(15)
        self.capture.side_effect = Exception("capture is down")
        with pytest.raises(Exception, match="capture is down"):
            self.run_at(30)
        self.capture.side_effect = None
        self.run_at(45)

        assert self.capture.call_count == 2

    def test_does_nothing_outside_cloud(self) -> None:
        with patch("posthog.quota_spine_comparison.is_cloud", return_value=False):
            compare_with_spine(RUN)

        self.get_limiting.assert_not_called()


class TestGetLimiting:
    license = License(key="key123::secret123")

    @patch("ee.billing.billing_manager.http_session.post")
    def test_posts_the_orgs_as_a_system_call(self, post: MagicMock) -> None:
        post.return_value = MagicMock(status_code=200, json=MagicMock(return_value=spine(UNDER)))

        result = BillingManager(self.license).get_limiting(["org-1"])

        assert result == spine(UNDER)
        (url,) = post.call_args.args
        assert url == "https://billing.posthog.com/api/internal/limiting"
        assert post.call_args.kwargs["json"] == {"organization_ids": ["org-1"]}
        token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        payload = jwt.decode(token, "secret123", algorithms=["HS256"], audience="posthog:license-key")
        assert payload["service_action"] == "limiting"
        assert "organization_id" not in payload

    @patch("ee.billing.billing_manager.http_session.post", return_value=MagicMock(status_code=404))
    def test_a_billing_without_the_endpoint_is_an_error_not_an_empty_answer(self, post: MagicMock) -> None:
        with pytest.raises(Exception):
            BillingManager(self.license).get_limiting([])
