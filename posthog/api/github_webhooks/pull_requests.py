"""Canonical PR analytics for product-owned and external pull requests."""

import uuid

import structlog
import posthoganalytics

from posthog.api.github_webhooks.attribution import _merged_by_attribution, _resolve_github_login_distinct_id
from posthog.api.github_webhooks.contracts import PullRequestAttribution
from posthog.api.github_webhooks.integrations import _resolve_external_team
from posthog.api.github_webhooks.metrics import GitHubWebhookAnalyticsEvent, observe_github_webhook_pr_event_dropped
from posthog.event_usage import groups

logger = structlog.get_logger(__name__)


# Nulled on external PRs so their schema matches task-originated PR events.
_TASK_ATTRIBUTION_KEYS = ("task_id", "run_id", "origin_product", "signal_report_id", "environment", "mode", "title")

# What a PR says, rather than how big it is. Attributed PRs can opt into these values; an
# external PR's own words are customer business context, so it gets the keys as nulls for
# schema parity, the same way _TASK_ATTRIBUTION_KEYS works.
_PR_CONTENT_KEYS = (
    "pr_title",
    "pr_body",
    "pr_body_truncated",
    "pr_labels",
    "pr_requested_reviewers",
    "pr_is_draft",
)

# A PR body is the biggest string on the delivery, and an agent-authored one can run long.
# Cap it so one verbose body cannot push the event past the capture size limit.
_PR_BODY_MAX_CHARS = 10_000


def _account_type(payload: dict) -> str | None:
    """Whether the webhook's repo is owned by a GitHub org or a personal account.

    ``repository.owner.type`` is "Organization" or "User"; the top-level
    ``organization`` object is present only for org-owned repos and backs it up
    when the owner block is missing. Returns None when neither signal is present.
    """
    owner_type = ((payload.get("repository") or {}).get("owner") or {}).get("type")
    if owner_type == "Organization":
        return "organization"
    if owner_type == "User":
        return "personal"
    if payload.get("organization"):
        return "organization"
    return None


def _pr_payload_properties(payload: dict) -> dict:
    pull_request = payload.get("pull_request") or {}
    return {
        "pr_url": pull_request.get("html_url"),
        "pr_number": pull_request.get("number"),
        "pr_author": (pull_request.get("user") or {}).get("login"),
        "pr_base_ref": (pull_request.get("base") or {}).get("ref"),
        "pr_head_ref": (pull_request.get("head") or {}).get("ref"),
        "pr_additions": pull_request.get("additions"),
        "pr_deletions": pull_request.get("deletions"),
        "pr_changed_files": pull_request.get("changed_files"),
        "pr_commits": pull_request.get("commits"),
        "account_type": _account_type(payload),
        "repo_owner_type": ((payload.get("repository") or {}).get("owner") or {}).get("type"),
    }


def _pr_content_properties(payload: dict) -> dict:
    """What a task-authored PR says: its title, body, labels, requested reviewers, draft state."""
    pull_request = payload.get("pull_request") or {}
    body = pull_request.get("body") or ""
    return {
        "pr_title": pull_request.get("title"),
        "pr_body": body[:_PR_BODY_MAX_CHARS],
        "pr_body_truncated": len(body) > _PR_BODY_MAX_CHARS,
        "pr_labels": [label.get("name") for label in (pull_request.get("labels") or []) if label.get("name")],
        "pr_requested_reviewers": [
            reviewer.get("login")
            for reviewer in (pull_request.get("requested_reviewers") or [])
            if reviewer.get("login")
        ],
        "pr_is_draft": pull_request.get("draft"),
    }


def pr_state_for_action(action: str | None, pull_request: dict) -> str | None:
    if action in ("opened", "reopened"):
        return "draft" if pull_request.get("draft") else "open"
    if action == "ready_for_review":
        return "open"
    if action == "converted_to_draft":
        return "draft"
    if action == "closed":
        return "merged" if pull_request.get("merged") else "closed"
    return None


def capture_pr_event(
    payload: dict,
    attribution: PullRequestAttribution | None,
    event: GitHubWebhookAnalyticsEvent,
) -> None:
    """Emit a canonical PR event with product attribution, or the external-PR fallback."""
    try:
        if attribution is None:
            team = _resolve_external_team(payload)
            if team is None:
                observe_github_webhook_pr_event_dropped(analytics_event=event, reason="unresolved_installation")
                return
            attribution = PullRequestAttribution(
                source="external",
                team_id=team.id,
                distinct_id=str(team.uuid),
                groups=groups(team=team),
                properties={
                    **dict.fromkeys(_TASK_ATTRIBUTION_KEYS, None),
                    "repository": ((payload.get("repository") or {}).get("full_name") or "").strip().lower() or None,
                },
            )

        properties = {**attribution.properties, **_pr_payload_properties(payload)}
        distinct_id = attribution.distinct_id
        if event == "pr_merged":
            merger_properties, merger_distinct_id = _merged_by_attribution(payload, attribution.team_id)
            properties.update(merger_properties)
            distinct_id = merger_distinct_id or distinct_id
        elif event == "pr_reviewed":
            review = payload.get("review") or {}
            reviewer = review.get("user") or {}
            reviewer_distinct_id = _resolve_github_login_distinct_id(reviewer.get("login"), attribution.team_id)
            properties.update(
                {
                    "pr_review_state": review.get("state"),
                    "pr_reviewed_by_login": reviewer.get("login"),
                    "pr_reviewed_by_id": reviewer.get("id"),
                }
            )
            if reviewer_distinct_id is not None:
                properties["pr_reviewed_by_distinct_id"] = reviewer_distinct_id
                distinct_id = reviewer_distinct_id

        properties.update(
            _pr_content_properties(payload) if attribution.include_content else dict.fromkeys(_PR_CONTENT_KEYS, None)
        )
        properties.update({"team_id": attribution.team_id, "pr_source": attribution.source})
        pr_url = (payload.get("pull_request") or {}).get("html_url")
        review_suffix = f":{(payload.get('review') or {}).get('id')}" if event == "pr_reviewed" else ""
        event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:{event}{review_suffix}"))
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event,
            properties=properties,
            groups=dict(attribution.groups),
            uuid=event_uuid,
            send_feature_flags=attribution.send_feature_flags,
        )
    except Exception as error:
        observe_github_webhook_pr_event_dropped(analytics_event=event, reason="capture_exception")
        logger.warning("github_pr_webhook_capture_failed", analytics_event=event, error=str(error))
