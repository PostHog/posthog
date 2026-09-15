"""
Pull-based delivery of Salesforce Task decisions into controlled relationships.

A controlled relationship definition binds the warehouse view whose rows fill it
(``AccountRelationshipDefinition.claim_saved_query``, read while ``claims_enabled``), so a project can
feed as many relationships as it has views. Each view maps the frozen decision fields on Salesforce
Tasks onto one row per Task with these columns:

- ``task_id``: the Task id; the idempotency key of the decision.
- ``organization_id``: the PostHog organization the Task's account is linked to.
- ``region``: the PostHog region the organization lives in (``us``, ``eu``).
- ``assignee_user_id``: PostHog user id of the allocated holder.
- ``source_assignee_id``: Salesforce user id of the same person.
- ``allocated_at``: when the eligible allocation was made at the source; never a delivery time.
- ``released_at``: when the Task was disqualified, or null while the allocation stands.
- ``source_releaser_id``: Salesforce user id of whoever disqualified the Task, or null.

Each run reads every row with a usable ``task_id``, in pages ordered by that id, and applies it: a
row without ``released_at`` claims the relationship, one with it withdraws that same Task's claim.
Both are idempotent, so rereading a Task costs one lookup and changes nothing; the view is expected
to keep only recent Tasks. A Task listed more than once is not applied at all, so a view must
express a release by setting ``released_at`` on the Task's one row, never by adding a second row.
Paging compares the id as text, so a row whose ``task_id`` is null or empty is not read and reaches
no outcome count; it carries no idempotency key, so no run could apply it safely. Timestamps without
a timezone are read as UTC, which is how Salesforce records them. Nothing is written back to
Salesforce: accepted and released claims are visible on the account's relationships and audit trail,
and every outcome is counted and logged here.
"""

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.apps import apps
from django.db import IntegrityError, transaction
from django.db.models import Q

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import ownership, relationships
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition

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
    """The claim binding cannot be made or used: no such definition or view, a definition that is not
    controlled, or a view that does not answer one of the documented decision columns."""


class SweepStopped(Exception):
    """The caller asked the sweep to stop, which it does between two pages or two decisions."""


def _never() -> bool:
    return False


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
# A run holds every row of the view before it applies the first decision, on a worker it shares with
# other products. The view is expected to hold recent Tasks only, so a read past this ceiling is a
# view to narrow rather than a sweep to attempt.
MAX_DECISION_ROWS = MAX_SELECT_RETURNED_ROWS


# The definitions a sweep fills. The coordinator wakes the teams that have one and the sweep reads
# them, so both ask the same question here.
CLAIM_BOUND = Q(is_controlled=True, claims_enabled=True, claim_saved_query__isnull=False)


def list_ownership_claim_team_ids() -> list[int]:
    """Every team with at least one definition the sweep fills; the coordinator reads this across
    teams, which is why the query is unscoped."""
    return list(
        AccountRelationshipDefinition.objects.unscoped()
        .filter(CLAIM_BOUND)
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()
    )


def claim_bound_definitions(team_id: int) -> list[AccountRelationshipDefinition]:
    return list(
        AccountRelationshipDefinition.objects.for_team(team_id)
        .filter(CLAIM_BOUND)
        .select_related("claim_saved_query")
        .order_by("name")
    )


def _locked_definition(team_id: int, definition_id: UUID) -> AccountRelationshipDefinition:
    """The definition under its row lock; call inside ``transaction.atomic()``."""
    definition = ownership.lock_definition(team_id, definition_id)
    if definition is None:
        raise ClaimSourceMisconfigured(f"No relationship definition {definition_id} in this project")
    return definition


def bind_claim_view(team_id: int, definition_id: UUID, saved_query_id: UUID | None) -> AccountRelationshipDefinition:
    """Bind the warehouse view whose rows fill the definition, or unbind it with None, which also
    switches its sweep off. Only a controlled definition can take a view, because a claim fills only
    a managed relationship; the view must answer every decision column; and a view feeds one
    definition, because a Task id is unique per team and a second definition would only ever see
    ``already_applied``."""
    with transaction.atomic():
        definition = _locked_definition(team_id, definition_id)
        view = None
        if saved_query_id is not None:
            if not definition.is_controlled:
                raise ClaimSourceMisconfigured(
                    f"{definition.name} is not controlled; a claim can only fill a controlled relationship"
                )
            saved_query_model = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
            view = saved_query_model.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
            if view is None:
                raise ClaimSourceMisconfigured(f"No warehouse view {saved_query_id} in this project")
            check_decision_columns(view.name, view.columns)
            elsewhere = (
                AccountRelationshipDefinition.objects.for_team(team_id)
                .filter(claim_saved_query=view)
                .exclude(id=definition.id)
                .first()
            )
            if elsewhere is not None:
                raise ClaimSourceMisconfigured(
                    f"View {view.name} already fills {elsewhere.name}; a view feeds one definition"
                )
        definition.claim_saved_query = view
        if view is None:
            definition.claims_enabled = False
        definition.save(update_fields=["claim_saved_query", "claims_enabled", "updated_at"])
        return definition


def set_claims_enabled(team_id: int, definition_id: UUID, enabled: bool) -> AccountRelationshipDefinition:
    """Switch the sweep for the definition's view. Enabling needs a bound view, so an enabled
    definition always names what the sweep reads."""
    with transaction.atomic():
        definition = _locked_definition(team_id, definition_id)
        if enabled and definition.claim_saved_query_id is None:
            raise ClaimSourceMisconfigured(
                f"{definition.name} has no claim view bound; bind one before enabling claims"
            )
        definition.claims_enabled = enabled
        definition.save(update_fields=["claims_enabled", "updated_at"])
        return definition


def reconcile_ownership_claims(team: Team, *, should_stop: Callable[[], bool] = _never) -> ClaimReconciliation:
    """Read every view bound to one of the project's definitions and apply the decisions in it to
    that definition. A project with nothing bound is skipped, so the scheduled sweep can run for every
    team, and a view that cannot be read is counted as ``misconfigured`` while the others still run.
    Callers must not run two sweeps for one team at once: an older read could apply a claim that
    a newer read has already seen released. The schedule guarantees this through a fixed workflow id
    per team, a single attempt per sweep, and ``should_stop``, which a timed-out activity sets so its
    thread stops between two pages or two decisions; at most the one decision already in flight can
    still commit beside the next sweep, and the tick after that repairs it."""
    bound: list[tuple[AccountRelationshipDefinition, Any]] = []
    for definition in claim_bound_definitions(team.id):
        view = definition.claim_saved_query
        if view is None:
            continue
        if view.deleted:
            logger.warning(
                "ownership_claims.view_deleted", team_id=team.id, definition_id=str(definition.id), view_id=str(view.id)
            )
            continue
        bound.append((definition, view))
    if not bound:
        return ClaimReconciliation(team_id=team.id, decisions=0, outcomes={}, skipped=True)
    decisions = 0
    outcomes: Counter[str] = Counter()
    for definition, view in bound:
        # One unusable view must not stop the project's other definitions: it is counted, reported,
        # and read again next tick. A stop request is a different exception and still ends the sweep.
        try:
            check_decision_columns(view.name, view.columns)
            rows = _read_decision_rows(team, view.name, should_stop)
        except ClaimSourceMisconfigured as error:
            capture_exception(error, {"team_id": team.id, "definition_id": str(definition.id)})
            logger.warning(
                "ownership_claims.view_misconfigured",
                team_id=team.id,
                definition_id=str(definition.id),
                view_id=str(view.id),
                error=str(error),
            )
            outcomes["misconfigured"] += 1
            continue
        decisions += len(rows)
        outcomes.update(_apply_rows(team, definition, rows, should_stop))
    return ClaimReconciliation(team_id=team.id, decisions=decisions, outcomes=dict(outcomes))


def _apply_rows(
    team: Team, definition: AccountRelationshipDefinition, rows: list[dict[str, Any]], should_stop: Callable[[], bool]
) -> dict[str, int]:
    outcomes: Counter[str] = Counter()
    for decision in _decisions_by_task(rows, outcomes):
        if should_stop():
            raise SweepStopped()
        # A collision on the per-source reference index is one decision an overlapping sweep accepted
        # first, so it is counted and the run goes on. Every refusal is an outcome, so anything else that raises is
        # the infrastructure or a bug, never one bad decision: it ends the sweep, and the next tick
        # reads the view again.
        try:
            if decision.is_release:
                result = release(team=team, decision=decision)
            else:
                result = claim(team=team, definition=definition, decision=decision)
        except IntegrityError as error:
            capture_exception(error, {"team_id": team.id, "source_ref": decision.source_ref})
            outcomes["error"] += 1
            continue
        if result.reason == "binding_changed":
            # The view's rows now belong to another definition, or to none; the next tick reads them
            # under the binding of that moment.
            outcomes["binding_changed"] += 1
            break
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
    """One decision per Task. The view promises one row per Task, so a Task listed more than once is
    counted and not applied at all, whether or not each of its rows is otherwise valid: the rows could
    disagree, and applying either could be wrong."""
    listings = Counter(_task_id(row) for row in rows)
    duplicated = {task_id for task_id, count in listings.items() if task_id is not None and count > 1}
    if duplicated:
        # Incrementing by zero would still list "duplicate" among a clean run's outcomes.
        outcomes["duplicate"] += len(duplicated)
    decisions: list[contracts.OwnershipClaimDecision] = []
    for row in rows:
        if _task_id(row) in duplicated:
            continue
        decision = _decision_from_row(row)
        if decision is None:
            outcomes["invalid"] += 1
        else:
            decisions.append(decision)
    return decisions


def _task_id(row: dict[str, Any]) -> str | None:
    try:
        return _identifier(row["task_id"])
    except ValueError:
        return None


def _read_decision_rows(team: Team, view_name: str, should_stop: Callable[[], bool]) -> list[dict[str, Any]]:
    """Every row of the view, keyed by column name, paged on ``task_id`` so a view of any size is read
    to the end. The view runs as a userless system read, so user-scoped warehouse access control is
    bypassed; tenant isolation still holds through the team."""
    rows: list[dict[str, Any]] = []
    cursor = ""
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.ACCOUNTS, team_id=team.pk):
        while True:
            if should_stop():
                raise SweepStopped()
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
            try:
                response = execute_hogql_query(
                    query, team=team, workload=Workload.OFFLINE, bypass_warehouse_access_control=True
                )
            except (ExposedHogQLError, ExposedCHQueryError) as error:
                # A view whose SQL no longer resolves (a dropped source table, a renamed column) is
                # the view's fault and is reported as such; infrastructure failures still propagate.
                raise ClaimSourceMisconfigured(f"View {view_name} cannot be read: {error}") from error
            page = response.results or []
            if len(page) < DECISION_PAGE_SIZE:
                rows.extend(dict(zip(DECISION_COLUMNS, row)) for row in page)
                return rows
            # A full page can end between two rows of one Task, and the next page starts after the
            # cursor, so the last Task is handed back to the next page unless it fills this one alone.
            last = str(page[-1][0])
            kept = [row for row in page if str(row[0]) != last] or page
            rows.extend(dict(zip(DECISION_COLUMNS, row)) for row in kept)
            if len(rows) > MAX_DECISION_ROWS:
                raise ClaimSourceMisconfigured(
                    f"View {view_name} holds more than {MAX_DECISION_ROWS} rows; narrow it to recent Tasks"
                )
            next_cursor = str(kept[-1][0])
            if next_cursor <= cursor:
                # The page filter compares toString(task_id) in ClickHouse while the cursor is the
                # Python str() of the value; a column type where the two disagree would return the
                # same page forever.
                raise ClaimSourceMisconfigured(f"View {view_name} column task_id does not page as text")
            cursor = next_cursor


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
    # A warehouse column with decimal places is read as Decimal, which has no is_integer(), so a
    # fractional value would reach int() and truncate onto another user's id.
    if (
        isinstance(value, bool)
        or (isinstance(value, float) and not value.is_integer())
        or (isinstance(value, Decimal) and not (value.is_finite() and value == value.to_integral_value()))
    ):
        raise ValueError(f"user id is not integral: {value!r}")
    return int(value)  # type: ignore[call-overload]


def _as_datetime(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def claim(
    *, team: Team, definition: AccountRelationshipDefinition, decision: contracts.OwnershipClaimDecision
) -> contracts.OwnershipClaimResult:
    """Apply an initial allocation frozen on a Salesforce Task to the definition whose view listed it.

    Under the Account lock, an accepted claim for the same Task is recognized first, so a Task read
    again on a later run is answered with the original decision even after the relationship has
    changed hands. A new Task may fill the relationship only when the account manages it, it is
    empty, the assignee is a member, and the allocation is later than the control timestamp, the
    last human decision, by more than the clock-skew allowance. Every refusal is returned as an
    outcome for the reconciler to record.

    Neither a claim nor a release moves the control timestamp. Both carry Salesforce's decision time
    and are processed later, so moving it to the processing instant would fence out a Task allocated
    between the source event and this sweep.
    """
    actor = relationships.Actor(source=AccountRelationshipSource.SALESFORCE_CLAIM)
    with transaction.atomic():
        # Definition before account, the order every writer takes. The view was read before this
        # transaction, so the binding is checked again here: an operator may have moved the view
        # to another definition or switched its sweep off in between, and a claim under the old
        # definition would leave the Task unable to fill the new one.
        current = ownership.lock_definition(team.id, definition.id)
        if (
            current is None
            or not current.claims_enabled
            or current.claim_saved_query_id != definition.claim_saved_query_id
        ):
            return _claim_result("blocked", "binding_changed")
        try:
            locked_account = _lock_account_by_external_id(team.id, decision.organization_id)
        except AmbiguousAccountIdentity:
            return _claim_result("blocked", "identity_mismatch")
        if locked_account is None:
            return _claim_result("blocked", "account_not_found")
        accepted = _accepted_claim(team.id, decision.source_ref)
        if accepted is not None:
            if accepted.account_id != locked_account.id:
                return _claim_result("blocked", "identity_mismatch", accepted)
            return _claim_result("already_applied", None, accepted)

        control = ownership.control_for(locked_account, definition)
        if control is None:
            return _claim_result("blocked", "role_not_managed")
        if not ownership.region_matches(decision.region):
            return _claim_result("blocked", "identity_mismatch")
        membership = (
            OrganizationMembership.objects.select_related("user")
            .filter(organization_id=team.organization_id, user_id=decision.assignee_user_id, user__is_active=True)
            .first()
        )
        if membership is None:
            return _claim_result("blocked", "assignee_not_member")

        holder = relationships.active_relationships(team.id, locked_account, definition).first()
        if holder is not None:
            return _claim_result("rejected", "role_occupied", holder)
        fence = control.controlled_at
        rejection = ownership.allocation_rejection(decision.allocated_at, fence)
        if rejection is not None:
            return _claim_result("rejected", rejection)

        relationship = AccountRelationship.objects.for_team(team.id).create(
            team_id=team.id,
            account=locked_account,
            definition=definition,
            user=membership.user,
            source=actor.source,
            source_ref=decision.source_ref,
        )
        relationships.record_transition(
            account=locked_account,
            actor=actor,
            activity="role_claimed",
            definition=definition,
            relationship=relationship,
            previous_user=None,
            current_user=membership.user,
            controlled_at=fence,
            source_actor_id=decision.source_assignee_id,
            source_decided_at=decision.allocated_at,
            emit_event=True,
        )
        return _claim_result("accepted", None, relationship, fence)


def release(*, team: Team, decision: contracts.OwnershipClaimDecision) -> contracts.OwnershipClaimResult:
    """End the relationship that this Task's accepted claim created, and nothing else.

    A release needs no time fence: identity to the Task's own claim is the guard, so it cannot clear
    a holder assigned by a person or by another Task. Once a person has transferred or cleared the
    relationship, the Task no longer holds it and the release is a no-op.
    """
    actor = relationships.Actor(source=AccountRelationshipSource.SALESFORCE_CLAIM)
    held = _accepted_claim(team.id, decision.source_ref)
    if held is None:
        return _claim_result("not_held", None)
    with transaction.atomic():
        # The claim names the account to lock, and is then read again under that lock: a person may
        # have ended it in between, which is exactly what makes the release a no-op. An account
        # deleted in between takes its claim row with it, so the account check only completes the type.
        locked_account = relationships.lock_account(team.id, held.account_id)
        accepted = _accepted_claim(team.id, decision.source_ref)
        if locked_account is None or accepted is None or accepted.ended_at is not None:
            return _claim_result("not_held", None, accepted)

        relationships.end_rows(team.id, [accepted])
        control = ownership.control_for(locked_account, accepted.definition)
        controlled_at = control.controlled_at if control is not None else None
        relationships.record_transition(
            account=locked_account,
            actor=actor,
            activity="role_released",
            definition=accepted.definition,
            relationship=accepted,
            previous_user=accepted.user,
            current_user=None,
            controlled_at=controlled_at,
            source_actor_id=decision.source_releaser_id,
            source_decided_at=decision.released_at,
            emit_event=True,
        )
        return _claim_result("cleared", None, accepted, controlled_at)


def _accepted_claim(team_id: int, source_ref: str) -> AccountRelationship | None:
    return (
        AccountRelationship.objects.for_team(team_id)
        .select_related("definition", "user")
        .filter(source=AccountRelationshipSource.SALESFORCE_CLAIM, source_ref=source_ref)
        .first()
    )


class AmbiguousAccountIdentity(Exception):
    """More than one account of the team carries the external id, differing only by case."""


def _lock_account_by_external_id(team_id: int, external_id: str) -> Account | None:
    """Lock the account linked to the organization. The link is read again under the lock, because
    an account update between the lookup and the lock could have moved it to another organization.

    The unique constraint on external ids is case-sensitive while this lookup is not, so two
    accounts that differ only by case are refused rather than resolved to whichever sorts first.
    """
    account_ids = list(
        Account.objects.for_team(team_id).filter(external_id__iexact=external_id).values_list("id", flat=True)[:2]
    )
    if len(account_ids) > 1:
        raise AmbiguousAccountIdentity(external_id)
    locked = relationships.lock_account(team_id, account_ids[0]) if account_ids else None
    if locked is None or (locked.external_id or "").lower() != external_id.lower():
        return None
    return locked


def _claim_result(
    outcome: contracts.OwnershipClaimOutcome,
    reason: contracts.OwnershipClaimReason | None,
    relationship: AccountRelationship | None = None,
    controlled_at: datetime | None = None,
) -> contracts.OwnershipClaimResult:
    return contracts.OwnershipClaimResult(
        outcome=outcome,
        reason=reason,
        relationship_id=relationship.id if relationship is not None else None,
        controlled_at=controlled_at,
    )
