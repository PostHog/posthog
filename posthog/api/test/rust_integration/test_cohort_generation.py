"""
Integration tests for the Rust batch flag evaluation endpoint used by static cohort
generation (`get_cohort_actors_for_feature_flag`).

These cover the Django-client ↔ Rust-endpoint contract: internal-token auth, payload
shape, version pinning, pagination, and matched-person results, using the real
`batch_evaluate_flag_for_team` HTTP client against a live Rust service. The full Celery
task (paging loop, retries, cohort insert) is covered by Django unit tests with this
client mocked — this environment has no ClickHouse, so the task's static-cohort insert
cannot run here.

Requires `INTERNAL_REQUEST_TOKEN` to be set identically for this process and the Rust
service (see ci-rust-flags-integration.yml).
"""

import os
from typing import Any

import pytest

from conftest import DjangoAPI, TestDB, TestEnv  # type: ignore[attr-defined,unused-ignore]

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("SKIP_RUST_INTEGRATION_TESTS", "1") == "1",
        reason="Set SKIP_RUST_INTEGRATION_TESTS=0 to run",
    ),
    pytest.mark.skipif(
        not os.environ.get("INTERNAL_REQUEST_TOKEN"),
        reason="INTERNAL_REQUEST_TOKEN must be set (matching the Rust service) for batch evaluation tests",
    ),
]


def _person_uuid(db: TestDB, person_id: int) -> str:
    with db.persons_conn.cursor() as cur:
        cur.execute("SELECT uuid FROM posthog_person WHERE id = %s", (person_id,))
        row = cur.fetchone()
    assert row is not None, f"Person with id={person_id} not found"
    return str(row[0])


def _property_flag_filters(key: str, value: str, rollout_percentage: int = 100) -> dict[str, Any]:
    return {
        "groups": [
            {
                "properties": [{"key": key, "type": "person", "value": value, "operator": "exact"}],
                "rollout_percentage": rollout_percentage,
            }
        ]
    }


def test_batch_evaluation_returns_property_matched_persons(db: TestDB, api: DjangoAPI, env: TestEnv):
    from posthog.api.services.flags_service import batch_evaluate_flag_for_team

    # Property values are unique per test so the exact-match assertions below cannot
    # pick up persons leaked from another test (cleanup hiccup or service-side caching).
    premium = db.create_person(["cohort_gen_user1"], {"plan": "premium_match"})
    db.create_person(["cohort_gen_user2"], {"plan": "free"})

    flag = api.create_flag("cohort-gen-flag", _property_flag_filters("plan", "premium_match"))

    page = batch_evaluate_flag_for_team(
        team_id=env.team_id,
        project_id=env.project_id,
        flag_key="cohort-gen-flag",
        expected_version=flag["version"] or 0,
        cursor=0,
        limit=100,
    )

    assert page["matched_person_uuids"] == [_person_uuid(db, premium)]
    assert page["next_cursor"] is None
    assert page["errors_count"] == 0


def test_batch_evaluation_paginates_with_cursor(db: TestDB, api: DjangoAPI, env: TestEnv):
    from posthog.api.services.flags_service import batch_evaluate_flag_for_team

    person_ids = [db.create_person([f"cohort_gen_page_user{i}"], {"plan": "premium_paginate"}) for i in range(3)]
    expected_uuids = {_person_uuid(db, pid) for pid in person_ids}

    flag = api.create_flag("cohort-gen-paging-flag", _property_flag_filters("plan", "premium_paginate"))

    matched: set[str] = set()
    cursor = 0
    pages = 0
    while True:
        page = batch_evaluate_flag_for_team(
            team_id=env.team_id,
            project_id=env.project_id,
            flag_key="cohort-gen-paging-flag",
            expected_version=flag["version"] or 0,
            cursor=cursor,
            limit=1,
        )
        matched.update(page["matched_person_uuids"])
        pages += 1
        assert pages <= 10, "pagination should terminate"
        if page["next_cursor"] is None:
            break
        assert page["next_cursor"] > cursor, "cursor must advance"
        cursor = page["next_cursor"]

    assert matched == expected_uuids
    assert pages >= 3


def test_batch_evaluation_rejects_stale_flag_version(db: TestDB, api: DjangoAPI, env: TestEnv):
    from posthog.api.services.flags_service import FlagVersionConflictError, batch_evaluate_flag_for_team

    db.create_person(["cohort_gen_version_user"], {"plan": "premium_version"})
    flag = api.create_flag("cohort-gen-version-flag", _property_flag_filters("plan", "premium_version"))

    with pytest.raises(FlagVersionConflictError):
        batch_evaluate_flag_for_team(
            team_id=env.team_id,
            project_id=env.project_id,
            flag_key="cohort-gen-version-flag",
            expected_version=(flag["version"] or 0) + 999,
            cursor=0,
            limit=100,
        )
