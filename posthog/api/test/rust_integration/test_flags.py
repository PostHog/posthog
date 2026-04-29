"""
Rust /flags integration tests.

No Django test framework. Each test:
1. Inserts persons via psycopg2 (persons database)
2. Creates cohorts/flags via Django HTTP API (authenticated with personal API key)
3. Calls Rust /flags endpoint and asserts on the result
"""

import os
from typing import Any

import pytest

from conftest import DjangoAPI, TestDB, TestEnv, evaluate_flags  # type: ignore[attr-defined,unused-ignore]

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_RUST_INTEGRATION_TESTS", "1") == "1",
    reason="Set SKIP_RUST_INTEGRATION_TESTS=0 to run",
)


def _cohort_filters(*and_groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Build OR-of-AND cohort filters. With no args, returns an empty filter (for static cohorts)."""
    return {
        "properties": {
            "type": "OR",
            "values": [{"type": "AND", "values": conditions} for conditions in and_groups],
        }
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_realtime_cohort_with_person_properties(db: TestDB, api: DjangoAPI, env: TestEnv):
    db.create_person(["user1"], {"email": "test@posthog.com", "plan": "enterprise"})
    db.create_person(["user2"], {"email": "test@other.com", "plan": "free"})

    cohort = api.create_cohort(
        "Enterprise Users",
        _cohort_filters(
            [
                {"key": "email", "type": "person", "value": "@posthog.com", "operator": "icontains"},
                {"key": "plan", "type": "person", "value": "enterprise", "operator": "exact"},
            ],
        ),
    )

    api.create_flag(
        "enterprise-feature",
        {
            "groups": [
                {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort["id"]}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    assert evaluate_flags(env.api_token, "user1")["flags"]["enterprise-feature"]["enabled"] is True
    assert evaluate_flags(env.api_token, "user2")["flags"]["enterprise-feature"]["enabled"] is False


def test_multiple_or_conditions(db: TestDB, api: DjangoAPI, env: TestEnv):
    db.create_person(["premium"], {"subscription": "premium"})
    db.create_person(["enterprise"], {"subscription": "enterprise"})
    db.create_person(["free"], {"subscription": "free"})

    cohort = api.create_cohort(
        "Paid Users",
        _cohort_filters(
            [{"key": "subscription", "type": "person", "value": "premium", "operator": "exact"}],
            [{"key": "subscription", "type": "person", "value": "enterprise", "operator": "exact"}],
        ),
    )

    api.create_flag(
        "paid-feature",
        {
            "groups": [
                {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort["id"]}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    assert evaluate_flags(env.api_token, "premium")["flags"]["paid-feature"]["enabled"] is True
    assert evaluate_flags(env.api_token, "enterprise")["flags"]["paid-feature"]["enabled"] is True
    assert evaluate_flags(env.api_token, "free")["flags"]["paid-feature"]["enabled"] is False


def test_nested_cohorts(db: TestDB, api: DjangoAPI, env: TestEnv):
    db.create_person(["both"], {"country": "US", "verified": True})
    db.create_person(["outer_only"], {"country": "US", "verified": False})
    db.create_person(["inner_only"], {"country": "UK", "verified": True})

    inner = api.create_cohort(
        "Verified",
        _cohort_filters([{"key": "verified", "type": "person", "value": True, "operator": "exact"}]),
    )
    outer = api.create_cohort(
        "US Verified",
        _cohort_filters(
            [
                {"key": "country", "type": "person", "value": "US", "operator": "exact"},
                {"key": "id", "type": "cohort", "value": inner["id"]},
            ],
        ),
    )

    api.create_flag(
        "nested-flag",
        {
            "groups": [
                {
                    "properties": [{"key": "id", "type": "cohort", "value": outer["id"]}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    assert evaluate_flags(env.api_token, "both")["flags"]["nested-flag"]["enabled"] is True
    assert evaluate_flags(env.api_token, "outer_only")["flags"]["nested-flag"]["enabled"] is False
    assert evaluate_flags(env.api_token, "inner_only")["flags"]["nested-flag"]["enabled"] is False


def test_static_cohort(db: TestDB, api: DjangoAPI, env: TestEnv):
    member_id = db.create_person(["member"], {"email": "member@example.com"})
    db.create_person(["nonmember"], {"email": "other@example.com"})

    cohort = api.create_cohort("Static VIPs", is_static=True)
    db.add_to_static_cohort(member_id, cohort["id"])

    api.create_flag(
        "static-flag",
        {
            "groups": [
                {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort["id"]}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    assert evaluate_flags(env.api_token, "member")["flags"]["static-flag"]["enabled"] is True
    assert evaluate_flags(env.api_token, "nonmember")["flags"]["static-flag"]["enabled"] is False


def test_group_based_flag(db: TestDB, api: DjangoAPI, env: TestEnv):
    db.create_person(["group_user"], {"email": "user@company.com"})
    db.create_group("organization", 0, "org_123", {"plan": "enterprise"})
    db.create_group("organization", 0, "org_456", {"plan": "free"})

    api.create_flag(
        "group-feature",
        {
            "aggregation_group_type_index": 0,
            "groups": [
                {
                    "properties": [
                        {
                            "key": "plan",
                            "type": "group",
                            "value": "enterprise",
                            "operator": "exact",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    result = evaluate_flags(env.api_token, "group_user", groups={"organization": "org_123"})
    assert result["flags"]["group-feature"]["enabled"] is True

    result = evaluate_flags(env.api_token, "group_user", groups={"organization": "org_456"})
    assert result["flags"]["group-feature"]["enabled"] is False


def test_unknown_distinct_id(api: DjangoAPI, env: TestEnv):
    cohort = api.create_cohort(
        "Any Users",
        _cohort_filters([{"key": "plan", "type": "person", "value": "pro", "operator": "exact"}]),
    )
    api.create_flag(
        "unknown-user-flag",
        {
            "groups": [
                {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort["id"]}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    result = evaluate_flags(env.api_token, "totally_unknown_user_xyz")
    assert result["flags"]["unknown-user-flag"]["enabled"] is False


def test_disabled_flag(db: TestDB, api: DjangoAPI, env: TestEnv):
    db.create_person(["disabled_user"], {"plan": "enterprise"})

    api.create_flag(
        "active-flag",
        {
            "groups": [
                {
                    "properties": [{"key": "plan", "type": "person", "value": "enterprise", "operator": "exact"}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )
    api.create_flag(
        "disabled-flag",
        {
            "groups": [
                {
                    "properties": [{"key": "plan", "type": "person", "value": "enterprise", "operator": "exact"}],
                    "rollout_percentage": 100,
                }
            ],
        },
        active=False,
    )

    result = evaluate_flags(env.api_token, "disabled_user")
    assert result["flags"]["active-flag"]["enabled"] is True
    # Inactive flags are excluded from the response entirely
    assert "disabled-flag" not in result["flags"]


def test_realtime_cohort_without_backfill_falls_through_to_dynamic_eval(db: TestDB, api: DjangoAPI, env: TestEnv):
    """A Realtime cohort without a backfill timestamp should fall through to
    dynamic filter evaluation rather than querying the cohort_membership table."""
    db.create_person(["rt_user"], {"plan": "enterprise"})
    db.create_person(["rt_nonmatch"], {"plan": "free"})

    cohort = api.create_cohort(
        "Realtime No Backfill",
        _cohort_filters(
            [{"key": "plan", "type": "person", "value": "enterprise", "operator": "exact"}],
        ),
    )

    # Override cohort_type to 'realtime' while leaving last_backfill_person_properties_at NULL.
    # This simulates a realtime cohort that hasn't been backfilled yet.
    db.set_cohort_type(cohort["id"], "realtime")

    api.create_flag(
        "realtime-fallback-flag",
        {
            "groups": [
                {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort["id"]}],
                    "rollout_percentage": 100,
                }
            ],
        },
    )

    # Should match via dynamic filter evaluation (the fallback path)
    assert evaluate_flags(env.api_token, "rt_user")["flags"]["realtime-fallback-flag"]["enabled"] is True
    assert evaluate_flags(env.api_token, "rt_nonmatch")["flags"]["realtime-fallback-flag"]["enabled"] is False
