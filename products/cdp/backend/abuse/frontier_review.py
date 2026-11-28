"""Run the frontier review of a function once its burst of saves is over, and report it as `cdp abuse review`.
It only reports: nothing here acts on the verdict."""

import structlog

from products.cdp.backend.abuse import frontier, metrics, shadow
from products.cdp.backend.abuse.case_file import build_case_file
from products.cdp.backend.abuse.judge import Review, ReviewFailure, Verdict, review_case
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

EVENT = "cdp abuse review"


def review(team_id: int, hog_function_id: str) -> None:
    """Review the last saved version, even when it no longer alerts, was deleted, or no longer runs custom code, so a
    probe cannot hide by changing or deleting the function within the countdown."""
    hog_function = (
        HogFunction.objects.select_related("team__organization", "hog_function_template")
        .filter(team_id=team_id, id=hog_function_id)
        .first()
    )
    if hog_function is not None:
        review_latest(hog_function)


def review_latest(hog_function: HogFunction) -> None:
    """Score the latest version again and review it, unless a verdict already covers it or the switch went off."""
    team = hog_function.team
    if not (shadow.shadow_enabled(team) and shadow.frontier_review_switched_on(team)):
        metrics.FRONTIER_REVIEW_SKIPS.labels(frontier.SkipReason.SWITCHED_OFF.value).inc()
        return
    scored = shadow.score(hog_function)
    fingerprint = frontier.fingerprint(
        shadow.content_of(hog_function, hog_function.template), scored.rule_hits, scored.outbound_call
    )
    skipped = frontier.skip_reason(stored=frontier.stored_verdict(str(hog_function.id)), fingerprint=fingerprint)
    if skipped is not None:
        metrics.FRONTIER_REVIEW_SKIPS.labels(skipped.value).inc()
        return
    result = review_case(build_case_file(hog_function, scored), team_id=hog_function.team_id)
    shadow.capture(hog_function, scored, _review_properties(scored, result), event=EVENT)
    if isinstance(result, Review):
        metrics.FRONTIER_REVIEWS.labels(result.verdict.value).inc()
        _remember(hog_function, result.verdict, fingerprint)
    else:
        metrics.FRONTIER_REVIEWS.labels(result.reason.value).inc()


def _remember(hog_function: HogFunction, verdict: Verdict, fingerprint: str) -> None:
    """Only after the event is captured, so a failed capture retries the task and reviews again. A failure here never
    fails the task, because a retry would post the same review twice."""
    try:
        frontier.store_verdict(
            str(hog_function.id),
            verdict=verdict.value,
            parked=verdict is Verdict.TRUE_POSITIVE,
            fingerprint=fingerprint,
        )
    except Exception:
        logger.exception("cdp_abuse_frontier_verdict_not_stored", hog_function_id=str(hog_function.id))


def _review_properties(scored: shadow.ScoredHogFunction, result: Review | ReviewFailure) -> dict[str, object]:
    verdict = scored.verdict
    jev: dict[str, object] = {
        "rule_hits": [rule.value for rule in scored.rule_hits],
        "would_alert": scored.would_alert,
        "would_block": scored.would_block,
        "risk_score": None if verdict is None else verdict.risk_score,
        "jev_error": None if scored.failure is None else scored.failure.value,
        **({} if verdict is None else {f"score_{question}": score for question, score in verdict.scores.items()}),
    }
    if isinstance(result, ReviewFailure):
        return {**jev, "review_failure": result.reason.value, "refusal_category": result.refusal_category}
    return {
        **jev,
        "verdict": result.verdict.value,
        "confidence": result.confidence,
        "findings": list(result.findings),
        "suggested_action": result.suggested_action.value,
        "admin_reason": result.admin_reason,
        "review_model": result.model,
        "review_latency_ms": result.latency_ms,
        "review_input_tokens": result.input_tokens,
        "review_output_tokens": result.output_tokens,
    }
