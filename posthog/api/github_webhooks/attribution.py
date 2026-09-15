import structlog
from social_django.models import UserSocialAuth

from posthog.api.github_webhooks.metrics import GitHubWebhookAttributionOutcome, observe_github_webhook_attribution
from posthog.ingress.dispatch.database import bounded_statement_timeout, is_statement_timeout
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.facade.github import resolve_github_login_distinct_id

logger = structlog.get_logger(__name__)

# Cap the org-member lookup that attributes the merger (and reviewer). GitHub gives a
# pull_request delivery one short window and never retries it, and the merged branch runs
# functional side effects (merge bookkeeping, signal-report resolution, wizard wind-down)
# right after capture. A slow lookup on the request path can therefore cost the whole
# delivery, not just the analytics event. Bounding it degrades to no attribution instead.
_ATTRIBUTION_STATEMENT_TIMEOUT_MS = 800

# Models the org-member resolver reads. ReplicaRouter only sends a model to the replica when
# that model is named in READ_REPLICA_OPT_IN, so the set of aliases the lookup can touch is
# knowable up front.
_ATTRIBUTION_MODELS = (Team, User, OrganizationMembership, UserSocialAuth, UserIntegration, Integration)


def _resolve_github_login_distinct_id(login: str | None, team_id: int) -> str | None:
    """Distinct id of the org member matching a GitHub login, or None when unresolvable.

    Runs under a per-statement timeout so a slow member lookup cannot hold the webhook
    open past GitHub's delivery timeout (see ``_ATTRIBUTION_STATEMENT_TIMEOUT_MS``).
    """
    if not login:
        return None
    try:
        with bounded_statement_timeout(_ATTRIBUTION_STATEMENT_TIMEOUT_MS, models=_ATTRIBUTION_MODELS):
            resolved = resolve_github_login_distinct_id(str(login), team_id)
    except Exception as e:
        # timeout is meant to be the leading indicator for the cap we just installed, so it
        # has to mean "statement cancelled", not "any OperationalError" -- connection resets
        # and other DB incidents raise the same class and would drown the signal.
        outcome: GitHubWebhookAttributionOutcome = "timeout" if is_statement_timeout(e) else "error"
        observe_github_webhook_attribution(outcome=outcome)
        logger.warning(
            "github_webhook_login_resolution_failed", login=login, team_id=team_id, outcome=outcome, error=str(e)
        )
        return None
    if resolved is None:
        observe_github_webhook_attribution(outcome="unresolved")
        return None
    observe_github_webhook_attribution(outcome="resolved")
    return resolved


def _merged_by_attribution(payload: dict, team_id: int) -> tuple[dict, str | None]:
    """Identity of the GitHub user who merged the PR, resolved to a PostHog user when possible.

    Merging is the one unambiguous personal act in the loop, so when the merger's GitHub
    login maps to an org member the pr_merged event attributes to them. Without a match the
    event keeps the task's assigned user (an auto-resolved reviewer or fallback for
    auto-started reports), so a consumer tells the two apart by the presence of
    pr_merged_by_distinct_id.
    """
    merged_by = (payload.get("pull_request") or {}).get("merged_by") or {}
    login = merged_by.get("login")
    if not login:
        return {}, None
    properties: dict = {"pr_merged_by_login": login, "pr_merged_by_id": merged_by.get("id")}
    distinct_id = _resolve_github_login_distinct_id(login, team_id)
    if distinct_id is not None:
        properties["pr_merged_by_distinct_id"] = distinct_id
    return properties, distinct_id
