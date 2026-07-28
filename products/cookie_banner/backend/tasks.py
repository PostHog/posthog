import structlog
from celery import shared_task

from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.cookie_banner.backend.artifact import sync_cookie_banner_artifact
from products.cookie_banner.backend.models import CookieBannerConfig

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def sync_project_cookie_banner_artifacts(team_id: int) -> None:
    """The banner row lives on the project's root team but every environment serves it,
    so a config change rebuilds the artifact of each of the project's teams."""
    try:
        project_id = Team.objects.only("project_id").get(id=team_id).project_id
        teams = list(Team.objects.filter(project_id=project_id))
    except Team.DoesNotExist:
        logger.exception("Team does not exist", team_id=team_id)
        return
    for team in teams:
        sync_cookie_banner_artifact(team)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def sync_all_cookie_banner_artifacts() -> None:
    """Backstop for drift the config-change signal can't see: rotated tokens and
    environments created after the last banner save."""
    project_ids = set(CookieBannerConfig.objects.unscoped().values_list("team__project_id", flat=True))
    for team in Team.objects.filter(project_id__in=project_ids):
        sync_cookie_banner_artifact(team)
