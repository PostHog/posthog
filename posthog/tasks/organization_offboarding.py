import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.unattributed_recording_links import revoke_unattributed_recording_links

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def revoke_unattributed_recording_links_task(organization_id: str) -> None:
    revoked = revoke_unattributed_recording_links(organization_id)
    logger.info("unattributed_recording_links_revoked", organization_id=organization_id, revoked=revoked)
