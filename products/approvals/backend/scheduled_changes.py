"""Creation-time approval gating for feature-flag scheduled changes.

A ``ScheduledChange`` row is created ungated and later applied by the Celery task
``process_scheduled_changes`` via ``FeatureFlag.scheduled_changes_dispatcher``. Without this
module a scheduled change could flip a policy-gated field (enabling a flag, raising rollout)
with no approval. Here we evaluate the same approval actions the request-time gate uses
(``decorators._evaluate_gate``) against the change a scheduled row *would* apply, and — when an
enabled policy requires approval — create a pending ``ChangeRequest`` bound to the scheduled
change. The applier then keys off that binding (see ``process_scheduled_changes``).
"""

import logging
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from django.db import transaction
from django.http import HttpRequest

from products.approvals.backend import decorators
from products.approvals.backend.exceptions import ApprovalRequired, PolicyConflict
from products.approvals.backend.models import ChangeRequest, ChangeRequestState, ValidationStatus
from products.approvals.backend.notifications import send_approval_expired_notification
from products.approvals.backend.services import apply_change_request

if TYPE_CHECKING:
    from products.feature_flags.backend.models.feature_flag import FeatureFlag
    from products.feature_flags.backend.models.scheduled_change import ScheduledChange

logger = logging.getLogger(__name__)


class _GatedAction(NamedTuple):
    """The enabled approval action + policy that gates a scheduled change, plus the request-time
    gate context needed to evaluate it. Named so the slots can't be silently reordered at the one
    callsite that unpacks them (mirrors the structured ``GateResult`` returned by ``_evaluate_gate``).
    """

    action_class: Any
    policy: Any
    serializer: Any
    http_request: HttpRequest
    gate_args: tuple


def scheduled_change_serializer_data(flag: "FeatureFlag", payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Translate a scheduled-change payload into the serializer-shaped change it would apply.

    Thin wrapper over the shared ``build_scheduled_change_serializer_data`` that the apply-time
    dispatcher (``FeatureFlag.scheduled_changes_dispatcher``) also uses, so the gate sees exactly
    the change the applier would make. Returns ``None`` when the payload is malformed or its
    operation is unrecognized — the applier surfaces those errors at apply time, the gate simply
    declines to create a CR for a change it cannot interpret.
    """
    # Deferred: this module is imported by posthog.tasks, which feature_flags transitively imports —
    # an eager import would create a circular import at startup.
    from products.feature_flags.backend.models.feature_flag import (  # noqa: PLC0415
        build_scheduled_change_serializer_data,
    )

    return build_scheduled_change_serializer_data(flag, payload)


def _detect_gated_action(flag: "FeatureFlag", payload: dict[str, Any], user) -> Optional[_GatedAction]:
    """Detect the enabled approval action + policy that gates a scheduled change — no side effects.

    Runs only the request-time gate's *detection* (``action.detect`` + ``_check_policy_for_action``)
    against the flag's current state, so no ``ChangeRequest`` is created and no notification is sent.
    Returns ``(matched_action, matched_policy, serializer, http_request, gate_args)`` when an enabled
    policy gates the change the payload would apply, else ``None`` (approvals disabled, malformed
    payload, or no gated action matches). Shared by ``gate_scheduled_change`` (which then evaluates
    the gate to create/reuse a CR) and by the fire-time re-check that keeps creation-time and
    request-time gating in lockstep.
    """
    # Deferred: feature_flags' serializer/actions transitively import posthog.tasks, which imports
    # this module — eager imports would create a circular import at startup.
    from products.approvals.backend.actions.feature_flags import (  # noqa: PLC0415
        DisableFeatureFlagAction,
        EnableFeatureFlagAction,
        UpdateFeatureFlagAction,
    )
    from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer  # noqa: PLC0415

    team = flag.team
    organization = team.organization

    if not decorators._is_approvals_enabled(organization):
        return None

    serializer_data = scheduled_change_serializer_data(flag, payload)
    if serializer_data is None:
        return None

    feature_flag_actions = [EnableFeatureFlagAction, DisableFeatureFlagAction, UpdateFeatureFlagAction]

    # Build a partial-update serializer over the real flag so detect()/extract_intent() read the
    # change out of validated_data exactly as they do for an API-driven update.
    http_request = HttpRequest()
    http_request.user = user or flag.created_by  # type: ignore[assignment]
    http_request.method = "PATCH"
    context = {
        "request": http_request,
        "team_id": team.id,
        "project_id": team.project_id,
        "get_team": lambda: team,
        "get_organization": lambda: organization,
    }
    serializer = FeatureFlagSerializer(instance=flag, data=serializer_data, partial=True, context=context)
    if not serializer.is_valid():
        # An invalid change can't be applied either; let the applier surface the error.
        return None

    # The gate's serializer path reads the validated change from args[1] (update's validated_data).
    gate_args: tuple = (flag, dict(serializer.validated_data))

    for action_class in feature_flag_actions:
        try:
            if action_class.detect(http_request, serializer, *gate_args):
                policy = decorators._check_policy_for_action(action_class, team, organization)
                if policy:
                    return _GatedAction(action_class, policy, serializer, http_request, gate_args)
        except Exception:
            logger.exception(
                "Error detecting action for scheduled change",
                extra={"action": action_class.key, "flag_id": flag.id},
            )

    return None


def gate_scheduled_change(
    flag: "FeatureFlag",
    payload: dict[str, Any],
    user,
    current_change_request: Optional[ChangeRequest] = None,
) -> Optional[ChangeRequest]:
    """Evaluate the approval gate for a scheduled change and create a pending CR if required.

    Returns the created ``ChangeRequest`` when an enabled policy gates the change the scheduled
    payload would apply, otherwise ``None`` (no policy, approvals disabled, or the change doesn't
    match any gated action). Reuses the request-time gate's action detection and CR creation so
    creation-time gating and request-time gating stay in lockstep.

    ``current_change_request`` is the CR already bound to the schedule being (re)gated, if any.
    Re-gating an unchanged action after a payload edit legitimately rediscovers that same pending
    CR; passing it here lets us tell "reuse my own binding" apart from "bind to someone else's
    pending request" (see the duplicate handling below).

    Raises ``PolicyConflict`` when the change matches more than one enabled policy: a single
    ``ChangeRequest`` can only carry one approval, so binding one would let the other policy's
    gated change ride along unapproved. We fail closed rather than save the row ungated — callers
    surface this as a 400 (creation/update) or skip the change (copy / recurring re-gate).

    Raises ``ApprovalRequired`` when the only matching request is a pending or approved duplicate
    that is not this schedule's own binding: binding it would let this schedule fire another
    change's approval at a moment that approval never covered (the second-schedule / immediate-
    change-then-schedule bypass). Fail closed.
    """
    detection = _detect_gated_action(flag, payload, user)
    if detection is None:
        return None

    result = decorators._evaluate_gate(
        action_class=detection.action_class,
        request=detection.http_request,
        team=flag.team,
        organization=flag.team.organization,
        policy=detection.policy,
        view_or_serializer=detection.serializer,
        args=detection.gate_args,
        kwargs={},
    )

    if result.action == "policy_conflict":
        # Multiple enabled policies match this change. We can't bind a single CR that satisfies
        # all of them, and returning None here would save the schedule ungated and let the Celery
        # applier dispatch it with no approval. Fail closed.
        raise PolicyConflict(
            conflicting_policies=result.conflicting_policies,
            message=result.error_message or "This change matches multiple approval policies",
            guidance="Split your changes into separate scheduled changes to address each policy independently",
        )

    if result.action == "require_approval":
        return result.change_request

    if result.action == "duplicate":
        existing = result.change_request
        # Reusing a pending CR is only safe when it is *this* schedule's own binding — e.g. re-gating
        # an unchanged action after a payload edit rediscovers the CR already bound to the row. Any
        # other duplicate must fail closed:
        #   - A pending CR belonging to another schedule (or an immediate change) would, once bound
        #     here, let this schedule fire that approval at a time it never covered — e.g. create a
        #     future gated schedule, then a second schedule for the same flag/action at an earlier
        #     time that rides the same pending CR and applies early once approved.
        #   - An approved CR is likewise not ours to fire on our own timing.
        # The caller surfaces this as a 409 (creation/update) or skips the change (copy / recurring
        # re-gate).
        if (
            existing is not None
            and existing.state == ChangeRequestState.PENDING
            and current_change_request is not None
            and existing.id == current_change_request.id
        ):
            return existing
        if existing is not None:
            raise ApprovalRequired(
                change_request=existing,
                message=(
                    "A change for this feature flag is already awaiting approval or its scheduled "
                    "application. Wait for it to resolve before scheduling another change."
                ),
                required_approvers={},
                error_code="change_request_pending",
            )
        return None

    return None


def _unbound_change_is_now_gated(scheduled_change: "ScheduledChange", flag: "FeatureFlag") -> bool:
    """True when a schedule with no bound CR would flip a policy-gated field against the flag's
    *current* state.

    Detection only (no CR is created, no notification sent) — a fire-time re-check that closes the
    stale-read bypass where a change that was a harmless no-op at scheduling time becomes a real,
    policy-gated change by the time it fires because the flag drifted in between. Takes the flag the
    sweep already loaded rather than re-querying the row (and its team/organization) under the open
    transaction.
    """
    return _detect_gated_action(flag, scheduled_change.payload, scheduled_change.created_by) is not None


def _expire_change_request(change_request: ChangeRequest, scheduled_change: "ScheduledChange", reason: str) -> None:
    """Expire a scheduled change's bound CR (terminal state) and notify its requester.

    Centralizes the expire → save → log → notify ritual shared by the fire-window-closed (PENDING)
    and approved-but-stale branches of ``apply_gated_scheduled_change``. The notification mirrors
    ``expire_old_change_requests`` (the canonical expiry sweep), so whoever requested — and, in the
    stale case, approved — the change is told it was discarded instead of it silently vanishing.

    The notification is deferred with ``transaction.on_commit`` because this runs inside the sweep's
    ``transaction.atomic()``: emailing / realtime-dispatching before commit would fire even if the
    surrounding transaction later rolls back.
    """
    change_request.state = ChangeRequestState.EXPIRED
    change_request.save(update_fields=["state"])
    logger.info(
        reason,
        extra={
            "scheduled_change_id": scheduled_change.id,
            "change_request_id": str(change_request.id),
        },
    )

    def _notify() -> None:
        try:
            send_approval_expired_notification(change_request)
        except Exception:
            logger.warning(
                "Failed to send change-request expiry notification for scheduled change",
                extra={
                    "scheduled_change_id": scheduled_change.id,
                    "change_request_id": str(change_request.id),
                },
            )

    transaction.on_commit(_notify)


def apply_gated_scheduled_change(scheduled_change: "ScheduledChange", flag: "FeatureFlag") -> bool:
    """Decide what to do with a gated scheduled change at fire time.

    Returns ``True`` when the caller should dispatch the change through the normal
    ``scheduled_changes_dispatcher`` path (no binding CR and no policy now gates the change, or the
    CR has already been applied via the approved path here), and ``False`` when the change must be
    skipped (its CR is still pending and the fire window has closed, so the CR is expired and nothing
    is applied; or an unbound change would now flip a policy-gated field with no approval).

    - Bound CR is APPROVED and not stale: apply via ``apply_change_request`` (the approved,
      non-re-gating path) and return ``False`` so the caller does not dispatch again.
    - Bound CR is still PENDING: the fire window has closed (the row is only processed once
      ``scheduled_at <= now``), so mark the CR EXPIRED and return ``False`` — skip the change.
    - Bound CR is in any other terminal state (APPLIED/REJECTED/EXPIRED/FAILED): do not re-apply;
      return ``False``.
    - No bound CR: re-check the gate against the flag's *current* state. A schedule binds no CR when
      its change was a no-op at scheduling time (e.g. an enable scheduled while the flag was already
      active), but the flag can drift before the fire window — a stale-read bypass where the schedule
      would re-enable a since-disabled flag with the enable policy never consulted. If a policy now
      gates the change, fail closed (return ``False``, skip); otherwise dispatch as before (``True``).

    Must be called inside the sweep's ``transaction.atomic()``: the bound CR is re-fetched under a
    row lock so this decision reads the latest committed state and serializes with
    ``ChangeRequestService.approve()``.
    """
    if scheduled_change.change_request_id is None:
        return not _unbound_change_is_now_gated(scheduled_change, flag)

    # Re-fetch under a row lock rather than trusting the prefetched copy. The sweep locks only the
    # ScheduledChange rows (select_for_update(of=("self",))), so a concurrent approve() that flips
    # this CR PENDING→APPROVED between the sweep's SELECT and here would otherwise be read as
    # still-PENDING and wrongly expired below — dropping a valid approval. Locking blocks until any
    # in-flight approve() commits and reads its result (approve() takes the same CR lock first).
    # Scope to the schedule's team: the bound CR always shares its team, and it keeps the lookup
    # tenant-isolated (idor-lookup-without-team).
    change_request = ChangeRequest.objects.select_for_update().get(
        pk=scheduled_change.change_request_id, team_id=scheduled_change.team_id
    )

    if (
        change_request.state == ChangeRequestState.APPROVED
        and change_request.validation_status != ValidationStatus.STALE
    ):
        apply_change_request(change_request)
        return False

    if change_request.state == ChangeRequestState.PENDING:
        # Time window closed with no approval — expire the request (terminal) and skip the change.
        _expire_change_request(
            change_request,
            scheduled_change,
            "Expired pending change request for scheduled change past its fire window",
        )
        return False

    if change_request.state == ChangeRequestState.APPROVED:
        # Reachable only when STALE (the approved-and-not-stale case applied and returned above).
        # Expire it here (terminal) rather than leaning on the hourly expire_old_change_requests
        # sweep: for a recurring schedule the next re-gate runs immediately, and a stale-approved
        # CR left in [PENDING, APPROVED] would be rediscovered by the flag-scoped duplicate check
        # as a duplicate it can't reuse (reuse requires PENDING), raising ApprovalRequired and
        # retrying the schedule to exhaustion long before the sweep (expires_at is policy-tunable
        # and can be days out) would clear it.
        _expire_change_request(
            change_request,
            scheduled_change,
            "Expired approved-but-stale change request for scheduled change",
        )
        return False

    # APPLIED / REJECTED / EXPIRED / FAILED: nothing to apply.
    return False


def regate_recurring_scheduled_change(
    scheduled_change: "ScheduledChange", flag: "FeatureFlag"
) -> Optional[ChangeRequest]:
    """Create a fresh pending CR for the next occurrence of a recurring gated schedule.

    A bound ChangeRequest is single-use — it carries one occurrence's intent. When a recurring
    schedule advances to its next fire, re-run the gate against the flag's current state so the
    next occurrence is independently gated. Returns the new CR (or None if no policy now applies).
    Takes the flag the sweep already loaded rather than re-querying it.

    May raise ``PolicyConflict`` when the next occurrence would match multiple policies; the
    scheduled-change task's error handling then records the failure and stops advancing the
    schedule rather than dispatching the occurrence ungated.
    """
    return gate_scheduled_change(flag, scheduled_change.payload, scheduled_change.created_by)
