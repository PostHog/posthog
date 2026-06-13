from celery import shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit

from products.ai_observability.backend.api.community_skill_services import sync_community_skills_from_github

logger = get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sync_community_skills() -> None:
    """Reconcile the local community-skills catalog with the PostHog/community-skills repo.

    Operates on the instance-global CommunitySkill catalog (no team scope), so the team-scope
    audit is intentionally skipped.
    """
    try:
        result = sync_community_skills_from_github()
    except Exception:
        logger.exception("community_skills_sync_failed")
        raise
    logger.info("community_skills_sync_complete", **result)
