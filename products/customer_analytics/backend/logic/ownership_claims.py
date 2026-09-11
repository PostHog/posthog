"""
Pull-based delivery of Salesforce Task decisions into commercial role ownership.

A project binds a warehouse view that maps the frozen decision fields on Salesforce Tasks onto
one row per Task with these columns:

- ``task_id``: the Task id; the idempotency key of the decision.
- ``organization_id``: the PostHog organization the Task's account is linked to.
- ``region``: the PostHog region the organization lives in (``us``, ``eu``).
- ``assignee_user_id``: PostHog user id of the allocated account executive.
- ``source_assignee_id``: Salesforce user id of the same person.
- ``allocated_at``: when the eligible allocation was made at the source; never a delivery time.
- ``released_at``: when the Task was disqualified, or null while the allocation stands.
- ``source_releaser_id``: Salesforce user id of whoever disqualified the Task, or null.

Each run reads every row, in pages ordered by ``task_id``, and applies it: a row without
``released_at`` claims the AE role, one with it withdraws that same Task's claim. Both are
idempotent, so rereading a Task costs one lookup and changes nothing; the view is expected to keep
only recent Tasks. Timestamps without a timezone are read as UTC, which is how Salesforce records
them. Nothing is written back to Salesforce: accepted and released claims are visible on the
account's relationships and audit trail, and every outcome is counted and logged here.
"""

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from django.core.cache import cache

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic import relationships
from products.customer_analytics.backend.models import TeamCustomerAnalyticsConfig

logger = structlog.get_logger(__name__)

DECISION_COLUMNS = (
    "task_id",
    "organization_id",
    "region",
    "assignee_user_id",
    "source_assignee_id",
    "allocated_at",
    "released_at",
    "source_releaser_id",
)


class ClaimSourceMisconfigured(Exception):
    """The bound view does not answer one of the documented decision columns."""


@frozen
class ClaimReconciliation:
    team_id: int
    decisions: int
    outcomes: dict[str, int]
    skipped: bool = False


def check_decision_columns(view_name: str, columns: dict | None) -> None:
    """Raise unless the view answers every documented decision column."""
    missing = [column for column in DECISION_COLUMNS if column not in (columns or {})]
    if missing:
        raise ClaimSourceMisconfigured(f"View {view_name} has no column(s): {', '.join(missing)}")


DECISION_PAGE_SIZE = 1000
# Bounds a sweep that dies without releasing its lock; a normal sweep finishes in seconds.
SWEEP_LOCK_SECONDS = 30 * 60


def reconcile_ownership_claims(team: Team) -> ClaimReconciliation:
    """Read the project's bound view and apply every decision in it. A project with claims off, no
    usable view bound, or a sweep already running is skipped, so the scheduled sweep can run for
    every team. Two sweeps never overlap for one team: an older read could otherwise apply a claim
    that a newer read has already seen released."""
    config = get_or_create_team_extension(team, TeamCustomerAnalyticsConfig)
    view = config.ownership_claim_saved_query
    if not config.ownership_claims_enabled or view is None or view.deleted:
        if view is not None and view.deleted:
            logger.warning("ownership_claims.view_deleted", team_id=team.id, view_id=str(view.id))
        return ClaimReconciliation(team_id=team.id, decisions=0, outcomes={}, skipped=True)
    check_decision_columns(view.name, view.columns)

    lock_key = f"customer_analytics:ownership_claims:{team.id}"
    if not cache.add(lock_key, True, timeout=SWEEP_LOCK_SECONDS):
        logger.info("ownership_claims.sweep_already_running", team_id=team.id)
        return ClaimReconciliation(team_id=team.id, decisions=0, outcomes={}, skipped=True)
    try:
        rows = _read_decision_rows(team, view.name)
        return ClaimReconciliation(team_id=team.id, decisions=len(rows), outcomes=_apply_rows(team, rows))
    finally:
        cache.delete(lock_key)


def _apply_rows(team: Team, rows: list[dict[str, Any]]) -> dict[str, int]:
    outcomes: Counter[str] = Counter()
    for decision in _decisions_by_task(rows, outcomes):
        # Each decision is its own transaction, so one that raises (a unique-index collision with an
        # overlapping sweep, say) is counted and reported without abandoning the rest of the run.
        try:
            result = (
                relationships.release_initial_ae(team=team, decision=decision)
                if decision.is_release
                else relationships.claim_initial_ae(team=team, decision=decision)
            )
        except Exception as error:
            capture_exception(error, {"team_id": team.id, "source_ref": decision.source_ref})
            outcomes["error"] += 1
            continue
        outcome = result.outcome if result.reason is None else f"{result.outcome}:{result.reason}"
        outcomes[outcome] += 1
        logger.info(
            "ownership_claims.decision",
            team_id=team.id,
            source_ref=decision.source_ref,
            release=decision.is_release,
            outcome=result.outcome,
            reason=result.reason,
        )
    return dict(outcomes)


def _decisions_by_task(rows: list[dict[str, Any]], outcomes: Counter[str]) -> list[contracts.OwnershipClaimDecision]:
    """One decision per Task. A Task listed more than once is applied as its release when any of its
    rows carries one, because a released Task is never claimed; the extra rows are counted."""
    by_task: dict[str, contracts.OwnershipClaimDecision] = {}
    for row in rows:
        decision = _decision_from_row(row)
        if decision is None:
            outcomes["invalid"] += 1
            continue
        current = by_task.get(decision.source_ref)
        if current is not None:
            outcomes["duplicate"] += 1
            if current.is_release or not decision.is_release:
                continue
        by_task[decision.source_ref] = decision
    return list(by_task.values())


def _read_decision_rows(team: Team, view_name: str) -> list[dict[str, Any]]:
    """Every row of the view, keyed by column name, paged on ``task_id`` so a view of any size is read
    to the end. The view runs as a userless system read, so user-scoped warehouse access control is
    bypassed; tenant isolation still holds through the team."""
    rows: list[dict[str, Any]] = []
    cursor = ""
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS, team_id=team.pk):
        while True:
            query = ast.SelectQuery(
                select=[ast.Field(chain=[column]) for column in DECISION_COLUMNS],
                select_from=ast.JoinExpr(table=ast.Field(chain=[view_name])),
                where=ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Call(name="toString", args=[ast.Field(chain=["task_id"])]),
                    right=ast.Constant(value=cursor),
                ),
                order_by=[
                    ast.OrderExpr(expr=ast.Call(name="toString", args=[ast.Field(chain=["task_id"])]), order="ASC")
                ],
                limit=ast.Constant(value=DECISION_PAGE_SIZE),
            )
            page = execute_hogql_query(query, team=team, bypass_warehouse_access_control=True).results or []
            rows.extend(dict(zip(DECISION_COLUMNS, row)) for row in page)
            if len(page) < DECISION_PAGE_SIZE:
                return rows
            cursor = str(page[-1][0])


def _decision_from_row(row: dict[str, Any]) -> contracts.OwnershipClaimDecision | None:
    """The decision the row carries, or None when the view shaped it badly, so a single malformed
    row is counted rather than applied. Identifiers must be present and non-blank: a null Task id
    would otherwise give unrelated rows one idempotency key."""
    try:
        return contracts.OwnershipClaimDecision(
            source_ref=_identifier(row["task_id"]),
            organization_id=_identifier(row["organization_id"]),
            region=_identifier(row["region"]).lower(),
            assignee_user_id=_user_id(row["assignee_user_id"]),
            source_assignee_id=_identifier(row["source_assignee_id"]),
            allocated_at=_as_datetime(row["allocated_at"]),
            released_at=_as_datetime(row["released_at"]) if row["released_at"] is not None else None,
            source_releaser_id=_identifier(row["source_releaser_id"])
            if row["source_releaser_id"] is not None
            else None,
        )
    except (TypeError, ValueError) as error:
        logger.warning("ownership_claims.invalid_row", task_id=row.get("task_id"), error=str(error))
        return None


def _identifier(value: object) -> str:
    if value is None or not str(value).strip():
        raise ValueError("identifier is missing")
    return str(value).strip()


def _user_id(value: object) -> int:
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"user id is not integral: {value!r}")
    return int(value)  # type: ignore[call-overload]


def _as_datetime(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
