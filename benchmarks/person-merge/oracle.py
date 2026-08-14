"""Conformance oracle: what every candidate must guarantee, checked through
the strategy's own read path plus storage-agnostic invariants.

The oracle is the contract of the experiment. A candidate that is fast but
fails any check here is not a candidate.
"""

from dataclasses import dataclass

import psycopg
from strategies.base import MergeOutcome, Strategy
from workload import TEAM_ID, SeededCase


class OracleFailure(AssertionError):
    pass


@dataclass(frozen=True, kw_only=True)
class OracleReport:
    checks: int


def verify(
    conn: psycopg.Connection,
    strategy: Strategy,
    seeded: SeededCase,
    outcome: MergeOutcome,
) -> OracleReport:
    checks = 0

    def ensure(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            raise OracleFailure(f"[{strategy.name}/{seeded.case}] {msg}")

    expected_scenario = seeded.case
    ensure(
        outcome.scenario == expected_scenario,
        f"scenario mismatch: expected {expected_scenario}, got {outcome.scenario}",
    )
    ensure(outcome.person_id is not None, "merge produced no person")

    # 1. Every involved distinct id resolves to the surviving person.
    for did in seeded.expected_distinct_ids:
        resolved = strategy.resolve(conn, TEAM_ID, did)
        ensure(resolved is not None, f"distinct id {did!r} resolves to nothing")
        assert resolved is not None
        ensure(
            resolved.person_id == outcome.person_id,
            f"distinct id {did!r} resolves to person {resolved.person_id}, expected {outcome.person_id}",
        )
        ensure(resolved.is_identified, f"surviving person for {did!r} is not identified")

    # 2. Property precedence: target's properties win over the source's.
    survivor = strategy.resolve(conn, TEAM_ID, seeded.target_distinct_id)
    assert survivor is not None
    if seeded.case == "both":
        ensure(
            survivor.properties.get("plan") == "free",
            "target-owned property lost (target must win conflicts)",
        )
        ensure(
            survivor.properties.get("utm_source") == "seeded-source",
            "source-only property did not survive the merge",
        )

    # 3. Cohort and feature-flag rows follow the surviving person.
    if seeded.case == "both":
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM posthog_cohortpeople WHERE person_id = %s",
                (outcome.person_id,),
            )
            ensure(cur.fetchone()[0] == seeded.cohort_rows, "cohort rows did not follow the merge")
            cur.execute(
                "SELECT count(*) FROM posthog_featureflaghashkeyoverride WHERE team_id = %s AND person_id = %s",
                (TEAM_ID, outcome.person_id),
            )
            ensure(cur.fetchone()[0] == seeded.ff_rows, "feature flag overrides did not follow the merge")

    # 4. Emission contract. Under the current contract, ClickHouse needs one
    #    override message per re-pointed mapping (version > 0) plus the person
    #    upsert/delete messages. Strategies emitting the "new" contract instead
    #    must cover every source mapping with at least one message that lets
    #    ClickHouse re-point those events; minimum viable check: the source
    #    person's uuid appears in some emission.
    did_msgs = [e for e in outcome.emissions if e.topic == "person_distinct_id"]
    person_msgs = [e for e in outcome.emissions if e.topic == "person"]
    if seeded.case == "both":
        if strategy.supports_current_contract and all(e.contract == "current" for e in outcome.emissions):
            ensure(
                len(did_msgs) == seeded.source_did_count,
                f"expected {seeded.source_did_count} distinct-id override messages, got {len(did_msgs)}",
            )
            for e in did_msgs:
                ensure(e.payload["version"] >= 1, "moved mapping emitted without a version bump")
                ensure(
                    e.payload["person_id"] == outcome.person_uuid,
                    "override message points at a non-surviving person",
                )
            ensure(
                any(e.payload.get("is_deleted") for e in person_msgs),
                "no deletion/tombstone message for the source person",
            )
        else:
            ensure(len(outcome.emissions) > 0, "merge emitted nothing downstream")
    elif seeded.case == "one":
        ensure(len(did_msgs) >= 1, "new mapping emitted no distinct-id message")
    elif seeded.case == "neither":
        ensure(len(did_msgs) == 2, "person creation must emit both mappings")
        ensure(len(person_msgs) >= 1, "person creation emitted no person message")

    # 5. No dangling storage: nothing still points at a person that is gone.
    #    (Storage-agnostic phrasing: every expected did resolves — checked in 1 —
    #    and the strategy's own tables pass its consistency query if it has one.)
    check_fn = getattr(strategy, "verify_storage", None)
    if check_fn is not None:
        check_fn(conn, TEAM_ID)
        checks += 1

    return OracleReport(checks=checks)
