"""Shadow mode: score saved destinations and transformations with Jev and report each verdict. Nothing is blocked."""

import json
from collections.abc import Iterable
from dataclasses import replace
from enum import StrEnum
from typing import Any

from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture
from posthog.utils import absolute_uri, get_instance_region

from products.cdp.backend.abuse import metrics, rules
from products.cdp.backend.abuse.account import Account, AccountCutoffs, AccountTier
from products.cdp.backend.abuse.classifier import (
    AbuseVerdict,
    ClassificationFailed,
    FailureReason,
    HogFunctionContent,
    SetAsideReason,
    Thresholds,
    classify,
    content_hash,
    has_input_expression,
    public_inputs,
    public_mappings,
    public_schema,
)
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType, _is_draft_only_save
from products.cdp.backend.services.hog_function_content import comparable_content

logger = structlog.get_logger(__name__)

# Its JSON payload holds the thresholds, for example {"alert_threshold": 0.5, "block_threshold": 0.9,
# "control_threshold": 0.7}, and may override the account cutoffs, for example {"established_min_age_days": 30,
# "new_max_age_days": 14, "new_max_members": 2}.
FLAG = "cdp-abuse-classifier"
# A kill switch for backfill runs, evaluated without a team. Turning it off stops a run before its next function.
BACKFILL_FLAG = "cdp-abuse-classifier-backfill"
EVENT = "cdp abuse classification"
CLASSIFIED_TYPES = frozenset({HogFunctionType.DESTINATION, HogFunctionType.TRANSFORMATION})
# A legacy plugin transformation runs PostHog's plugin code, chosen by its template id, so its `hog` field never
# runs. Its inputs are still evaluated first.
_LEGACY_PLUGIN_PREFIX = "plugin-"
_HASH_TTL_SECONDS = 30 * 24 * 60 * 60
_BACKFILL_RUN_TTL_SECONDS = 14 * 24 * 60 * 60


class Trigger(StrEnum):
    SAVE = "save"
    BACKFILL = "backfill"
    EVAL = "eval"


@frozen
class ScoredHogFunction:
    content_hash: str
    code_modified_from_template: bool | None
    verdict: AbuseVerdict | None
    failure: FailureReason | None
    rule_hits: tuple[rules.Rule, ...]
    outbound_call: bool
    account: Account
    account_tier: AccountTier
    set_aside: dict[str, SetAsideReason]

    @property
    def would_alert(self) -> bool:
        return bool(self.rule_hits) or (self.verdict is not None and self.verdict.would_alert)

    @property
    def would_block(self) -> bool:
        blocked_by_rule = any(rule in rules.BLOCKING_RULES for rule in self.rule_hits)
        return blocked_by_rule or (self.verdict is not None and self.verdict.would_block)

    @property
    def label(self) -> str:
        if self.would_block:
            return "would_block"
        if self.would_alert:
            return "alert"
        return "clean" if self.verdict is not None else "none"


def content_of(hog_function: HogFunction, template: HogFunctionTemplate | None = None) -> HogFunctionContent:
    # Compiled values change on every recompile and add nothing for the model, so they stay out of the state and hash.
    config = comparable_content(
        {
            "inputs": hog_function.inputs,
            "filters": hog_function.filters,
            "mappings": hog_function.mappings,
            "masking": hog_function.masking,
        }
    )
    return HogFunctionContent(
        type=hog_function.type or "",
        template_id=hog_function.template_id,
        code_modified_from_template=None if template is None else hog_function.hog != template.code,
        hog=hog_function.hog or "",
        inputs_schema=public_schema(hog_function.inputs_schema),
        inputs=public_inputs(config["inputs"], hog_function.inputs_schema),
        filters=config["filters"] or {},
        mappings=public_mappings(config["mappings"]),
        masking=config["masking"] or None,
    )


def _flag_targeting(team: Team) -> dict[str, Any]:
    return {
        "groups": {"organization": str(team.organization_id), "project": str(team.id)},
        "group_properties": {
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id), "uuid": str(team.uuid)},
        },
        "send_feature_flag_events": False,
    }


def shadow_enabled(team: Team, *, only_evaluate_locally: bool = False) -> bool:
    """Fails closed: a flag error means nothing runs."""
    try:
        return (
            posthoganalytics.feature_enabled(
                FLAG, str(team.uuid), only_evaluate_locally=only_evaluate_locally, **_flag_targeting(team)
            )
            is True
        )
    except Exception:
        logger.warning("cdp_abuse_classifier_flag_check_failed", team_id=team.id, exc_info=True)
        return False


def backfill_enabled() -> bool:
    try:
        return (
            posthoganalytics.feature_enabled(
                BACKFILL_FLAG, BACKFILL_FLAG, only_evaluate_locally=True, send_feature_flag_events=False
            )
            is True
        )
    except Exception:
        logger.warning("cdp_abuse_classifier_backfill_flag_check_failed", exc_info=True)
        return False


def _flag_payload(team: Team) -> dict[str, Any]:
    try:
        # The flag has one payload. Asking for the "on" value returns it for teams the flag does not match too,
        # so a backfill scores every team against the same thresholds.
        payload = posthoganalytics.get_feature_flag_payload(
            FLAG, str(team.uuid), match_value=True, **_flag_targeting(team)
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
    except Exception:
        logger.warning("cdp_abuse_classifier_payload_unreadable", team_id=team.id, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _thresholds(payload: dict[str, Any], team_id: int) -> Thresholds:
    if not payload.keys() & {"alert_threshold", "block_threshold", "control_threshold"}:
        return Thresholds()
    try:
        control = {"control": float(payload["control_threshold"])} if "control_threshold" in payload else {}
        return Thresholds(alert=float(payload["alert_threshold"]), block=float(payload["block_threshold"]), **control)
    except (KeyError, TypeError, ValueError, OverflowError):
        logger.warning("cdp_abuse_classifier_thresholds_unreadable", team_id=team_id, exc_info=True)
        return Thresholds()


def _account_cutoffs(payload: dict[str, Any], team_id: int) -> AccountCutoffs:
    keys = ("established_min_age_days", "new_max_age_days", "new_max_members")
    try:
        return AccountCutoffs(**{key: _whole_number(payload[key]) for key in keys if key in payload})
    except (TypeError, ValueError):
        logger.warning("cdp_abuse_classifier_account_cutoffs_unreadable", team_id=team_id, exc_info=True)
        return AccountCutoffs()


def _whole_number(value: object) -> int:
    # Ints and strings skip float, which overflows on a huge int and rounds a long fractional string to whole.
    if isinstance(value, bool):
        raise TypeError(f"not a number: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"not a whole number: {value!r}")


def _account_of(team: Team) -> Account:
    organization = team.organization
    return Account(
        age=timezone.now() - organization.created_at,
        has_active_subscription=organization.has_active_subscription,
        member_count=OrganizationMembership.objects.filter(organization_id=organization.id).count(),
        cdp_trust_score=_cdp_trust_score(organization.customer_trust_scores),
    )


def _cdp_trust_score(trust_scores: object) -> int | None:
    # Billing keys trust scores by usage key, and CDP usage is counted as trigger events.
    score = trust_scores.get("cdp_trigger_events") if isinstance(trust_scores, dict) else None
    return score if isinstance(score, int) and not isinstance(score, bool) else None


@frozen
class _Scoring:
    thresholds: Thresholds
    account: Account
    account_tier: AccountTier


def _scoring_for(team: Team) -> _Scoring:
    payload = _flag_payload(team)
    account = _account_of(team)
    return _Scoring(
        thresholds=_thresholds(payload, team.id),
        account=account,
        account_tier=account.tier(_account_cutoffs(payload, team.id)),
    )


def _hash_key(hog_function_id: str) -> str:
    # Versioned with the format of `_cache_entry`, so workers on the previous format do not overwrite these entries
    # during a deploy, and each function scores once more after it.
    return f"cdp:abuse_classifier:content_hash:v3:{hog_function_id}"


def _backfill_scored_key(run_id: str, hog_function_id: str) -> str:
    return f"cdp:abuse_classifier:backfill:{run_id}:{hog_function_id}"


def scored_in_backfill(run_id: str, hog_function_id: str) -> bool:
    """Whether this run already delivered a verdict for the function, so a resumed run can skip it."""
    return cache.get(_backfill_scored_key(run_id, hog_function_id)) is not None


@receiver(post_save, sender=HogFunction, dispatch_uid="cdp.abuse.shadow_classify")
def hog_function_saved(
    sender: type[HogFunction], instance: HogFunction, update_fields: Iterable[str] | None = None, **kwargs: object
) -> None:
    if _is_draft_only_save(update_fields) or not is_scorable(instance):
        return
    transaction.on_commit(lambda: _queue_if_enabled(instance))


def _queue_if_enabled(hog_function: HogFunction) -> None:
    # Runs in the saving request after the commit, so a failure here must not fail the save, and the flag is
    # read from the polled definitions so a slow flag service cannot slow the save.
    try:
        if not shadow_enabled(hog_function.team, only_evaluate_locally=True):
            return
        # Checked after the flag, so the query runs only for enrolled teams.
        candidate = scorable_hog_functions(enabled_only=False).filter(pk=hog_function.pk).first()
        if candidate is None or not runs_customer_code(candidate):
            return

        from products.cdp.backend.tasks.abuse_classification import classify_hog_function_for_abuse  # noqa: PLC0415

        classify_hog_function_for_abuse.delay(team_id=hog_function.team_id, hog_function_id=str(hog_function.id))
    except Exception:
        logger.exception("cdp_abuse_classifier_queue_failed", hog_function_id=str(hog_function.id))


def is_scorable(hog_function: HogFunction) -> bool:
    """A disabled function is scored too: the editor's test invocation still runs it, and saving a probe disabled
    is itself a signal."""
    return not hog_function.deleted and hog_function.type in CLASSIFIED_TYPES


def scorable_hog_functions(*, enabled_only: bool = True) -> QuerySet[HogFunction]:
    """Destinations, and transformations that may run code a customer wrote. `enabled_only` keeps the running ones.

    A transformation runs without network access, so one that runs a template's code unchanged is PostHog's code.
    A destination from a template is still scored: its inputs, such as a webhook URL, can make it abusive.
    Input expressions cannot be told apart in SQL, and secret inputs are encrypted, so a template transformation
    with any inputs or a secret input is a candidate, and `runs_customer_code` decides.
    """
    # Code with no linked template or edited from it. A blank template's starter code counts as stock.
    may_run_custom_hog = ~Q(template_id__startswith=_LEGACY_PLUGIN_PREFIX) & (
        Q(hog_function_template__isnull=True) | ~Q(hog=F("hog_function_template__code"))
    )
    has_inputs = (Q(inputs__isnull=False) & ~Q(inputs={})) | Q(inputs_schema__contains=[{"secret": True}])
    may_run_custom_code = may_run_custom_hog | has_inputs
    return (
        HogFunction.objects.select_related("team__organization", "hog_function_template")
        .filter(deleted=False)
        .filter(**({"enabled": True} if enabled_only else {}))
        .filter(Q(type=HogFunctionType.DESTINATION) | (Q(type=HogFunctionType.TRANSFORMATION) & may_run_custom_code))
    )


def runs_customer_code(hog_function: HogFunction) -> bool:
    """For a candidate from `scorable_hog_functions`: a destination, or a transformation whose code was written or
    edited by the customer or whose inputs hold an expression. Secret inputs are checked here but never sent to Jev."""
    if hog_function.type != HogFunctionType.TRANSFORMATION or _runs_custom_hog(hog_function):
        return True
    return has_input_expression(hog_function.inputs, hog_function.inputs_schema) or has_input_expression(
        hog_function.encrypted_inputs, hog_function.inputs_schema
    )


def _runs_custom_hog(hog_function: HogFunction) -> bool:
    if (hog_function.template_id or "").startswith(_LEGACY_PLUGIN_PREFIX):
        return False
    template = hog_function.hog_function_template
    return template is None or hog_function.hog != template.code


def classify_if_due(hog_function: HogFunction) -> None:
    """Score and report a saved function, unless the flag went off or its content was scored since it was queued."""
    if not is_scorable(hog_function) or not runs_customer_code(hog_function) or not shadow_enabled(hog_function.team):
        return
    content = content_of(hog_function, hog_function.template)
    runtime_content = _with_secret_inputs(hog_function, content)
    rule_hits = rules.matched_rules(runtime_content)
    outbound_call = rules.has_outbound_call(runtime_content)
    set_aside = rules.set_aside_scores(runtime_content, rule_hits)
    scoring = _scoring_for(hog_function.team)
    public_content_hash = content_hash(content)
    reported = cache.get(_hash_key(str(hog_function.id)))
    # A verdict reported while enabled covers the same content saved disabled, so disabling a function reports nothing.
    covering_states = (True,) if hog_function.enabled else (True, False)
    if any(
        reported
        == _cache_entry(public_content_hash, rule_hits, outbound_call, scoring.account_tier, set_aside, enabled=state)
        for state in covering_states
    ):
        metrics.CLASSIFICATIONS.labels(hog_function.type, "none", "skipped_unchanged").inc()
        return
    report(
        hog_function,
        _score(hog_function, content, rule_hits, outbound_call, set_aside, scoring),
        trigger=Trigger.SAVE,
    )


def classify_for_backfill(hog_function: HogFunction, run_id: str) -> None:
    """Score regardless of the team flag and of an unchanged hash. The hash is still recorded."""
    if not is_scorable(hog_function) or not runs_customer_code(hog_function) or not backfill_enabled():
        return
    scored = score(hog_function)
    report(hog_function, scored, trigger=Trigger.BACKFILL, backfill_run_id=run_id)
    # Only a delivered verdict counts, so resuming the run retries failures and work the kill switch dropped.
    if scored.verdict is not None:
        cache.set(_backfill_scored_key(run_id, str(hog_function.id)), True, _BACKFILL_RUN_TTL_SECONDS)


def score(hog_function: HogFunction) -> ScoredHogFunction:
    content = content_of(hog_function, hog_function.template)
    runtime_content = _with_secret_inputs(hog_function, content)
    rule_hits = rules.matched_rules(runtime_content)
    return _score(
        hog_function,
        content,
        rule_hits,
        rules.has_outbound_call(runtime_content),
        rules.set_aside_scores(runtime_content, rule_hits),
        _scoring_for(hog_function.team),
    )


def _score(
    hog_function: HogFunction,
    content: HogFunctionContent,
    rule_hits: tuple[rules.Rule, ...],
    outbound_call: bool,
    set_aside: dict[str, SetAsideReason],
    scoring: _Scoring,
) -> ScoredHogFunction:
    verdict: AbuseVerdict | None = None
    failure: FailureReason | None = None
    try:
        verdict = classify(
            content,
            team_id=hog_function.team_id,
            thresholds=scoring.thresholds,
            set_aside=set_aside.keys(),
            account_tier=scoring.account_tier,
        )
    except ClassificationFailed as error:
        failure = error.reason
    return ScoredHogFunction(
        content_hash=content_hash(content),
        code_modified_from_template=content.code_modified_from_template,
        verdict=verdict,
        failure=failure,
        rule_hits=rule_hits,
        outbound_call=outbound_call,
        account=scoring.account,
        account_tier=scoring.account_tier,
        set_aside=set_aside,
    )


def _with_secret_inputs(hog_function: HogFunction, content: HogFunctionContent) -> HogFunctionContent:
    """The content with the values of secret inputs, which run as Hog templates like any other input. Only the
    rules read it, here in the worker, so the values never reach Jev, the content hash or the event."""
    config = comparable_content(
        {
            "inputs": {**(hog_function.inputs or {}), **_decrypted_secret_inputs(hog_function)},
            "mappings": hog_function.mappings,
        }
    )
    return replace(content, inputs=config["inputs"] or {}, mappings=config["mappings"] or [])


def _decrypted_secret_inputs(hog_function: HogFunction) -> dict[str, Any]:
    """Empty when the field returns the ciphertext as a string because its key is unavailable, so the public inputs
    still score."""
    secret_inputs = hog_function.encrypted_inputs
    return secret_inputs if isinstance(secret_inputs, dict) else {}


def _cache_entry(
    public_content_hash: str,
    rule_hits: tuple[rules.Rule, ...],
    outbound_call: bool,
    account_tier: AccountTier,
    set_aside: dict[str, SetAsideReason],
    *,
    enabled: bool,
) -> str:
    """The model sees only the public content, and secret inputs change only the rule hits, the outbound call and
    the scores set aside. Keeping all of them means a secret change that matches a rule or adds a call scores the
    function again, while the cache holds nothing more about a secret value than the event does. Only the established
    tier changes whether a moderate score alerts, so an account that enters or leaves it scores again on its next
    save. Enabling a function that was scored while disabled reports it again, so a probe that starts running alerts
    as enabled."""
    established = account_tier is AccountTier.ESTABLISHED
    reasons = ",".join(f"{question}={reason}" for question, reason in sorted(set_aside.items()))
    entry = f"{public_content_hash}:{','.join(rule_hits)}:{int(outbound_call)}:{int(established)}:{reasons}"
    return entry if enabled else f"{entry}:disabled"


def report(
    hog_function: HogFunction, scored: ScoredHogFunction, *, trigger: Trigger, backfill_run_id: str | None = None
) -> None:
    function_type = hog_function.type or ""
    run = {"trigger": trigger.value} | ({"backfill_run_id": backfill_run_id} if backfill_run_id else {})
    for rule in scored.rule_hits:
        metrics.RULE_HITS.labels(rule.value).inc()
    rule_hits = [rule.value for rule in scored.rule_hits]
    if scored.verdict is None:
        reason = scored.failure or FailureReason.GATEWAY_ERROR
        metrics.ERRORS.labels(reason.value).inc()
        metrics.CLASSIFICATIONS.labels(function_type, scored.label, "error").inc()
        # Without a model verdict, a function no rule matched is unknown rather than clean.
        rule_verdict = {"would_alert": scored.would_alert, "would_block": scored.would_block} if rule_hits else {}
        _capture(hog_function, scored, {**run, "error": reason.value, "rule_hits": rule_hits, **rule_verdict})
        return

    verdict = scored.verdict
    metrics.CLASSIFICATIONS.labels(function_type, scored.label, "ok").inc()
    metrics.RISK_SCORE.labels(function_type).observe(verdict.risk_score)
    metrics.LATENCY.observe(verdict.latency_ms / 1000)
    metrics.INPUT_TOKENS.labels(function_type).inc(verdict.input_tokens)
    _capture(
        hog_function,
        scored,
        {
            **run,
            **{f"score_{question}": probability for question, probability in verdict.scores.items()},
            "risk_score": verdict.risk_score,
            "rule_hits": rule_hits,
            "set_aside_scores": {question: reason.value for question, reason in scored.set_aside.items()},
            "would_alert": scored.would_alert,
            "would_block": scored.would_block,
            "model_alert_gates": [gate.value for gate in verdict.model_alert_gates],
            "state_truncated": verdict.state_truncated,
            "model": verdict.model,
            "latency_ms": verdict.latency_ms,
            "input_tokens": verdict.input_tokens,
        },
    )
    # Only a delivered verdict is remembered, so a failed classification or capture runs again on the next save.
    cache.set(
        _hash_key(str(hog_function.id)),
        _cache_entry(
            scored.content_hash,
            scored.rule_hits,
            scored.outbound_call,
            scored.account_tier,
            scored.set_aside,
            enabled=hog_function.enabled,
        ),
        _HASH_TTL_SECONDS,
    )


def _capture(hog_function: HogFunction, scored: ScoredHogFunction, outcome: dict[str, object]) -> None:
    team = hog_function.team
    account = scored.account
    properties = {
        "team_id": team.id,
        "organization_id": str(team.organization_id),
        "organization_created_at": team.organization.created_at.isoformat(),
        "organization_age_days": account.age.days,
        "organization_member_count": account.member_count,
        "has_active_subscription": account.has_active_subscription,
        "cdp_trust_score": account.cdp_trust_score,
        "account_tier": scored.account_tier.value,
        "hog_function_id": str(hog_function.id),
        "hog_function_type": hog_function.type,
        "template_id": hog_function.template_id,
        "code_modified_from_template": scored.code_modified_from_template,
        "outbound_call": scored.outbound_call,
        "enabled": hog_function.enabled,
        "content_hash": scored.content_hash,
        "admin_url": absolute_uri(f"/admin/cdp/hogfunction/{hog_function.id}/change/"),
        **outcome,
    }
    # Every region reports to PostHog's US project, so the region rides along as a property.
    with ph_scoped_capture(event_region=get_instance_region(), raise_on_error=True) as capture:
        capture(distinct_id=str(team.uuid), event=EVENT, properties=properties, groups=groups(team=team))
