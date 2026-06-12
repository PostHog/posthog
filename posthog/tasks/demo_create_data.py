from django.core.cache import cache

from celery import shared_task

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True)
@skip_team_scope_audit
def create_data_for_demo_team(team_id: int, user_id: int, cache_key: str) -> None:
    # Deferred: the demo matrix pulls mimesis (a fake-data generator). This task module is
    # eager-imported by posthog/tasks/__init__, so a module-level import drags mimesis onto
    # every process's startup path. Only needed when actually generating demo data.
    from posthog.demo.matrix import manager  # noqa: PLC0415
    from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix  # noqa: PLC0415

    team = Team.objects.get(pk=team_id)
    user = User.objects.get(pk=user_id)
    if team and user:
        manager.MatrixManager(HedgeboxMatrix(), use_pre_save=True).run_on_team(team, user)
        cache.delete(cache_key)
