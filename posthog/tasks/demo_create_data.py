from celery import shared_task
from sentry_sdk import capture_exception

from posthog.demo.matrix import manager```
from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix
from posthog.models.team.team import Team
from posthog.models.user import User


@shared_task(ignore_result=True)
def create_data_for_demo_team(team_id: int, user_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    user = User.objects.get(pk=user_id)
    if team and user:
        try:
            manager.MatrixManager(HedgeboxMatrix(), use_pre_save=True).run_on_team(team, user)
        except Exception as e:  # TODO: Remove this after 2022-12-22, the except is just temporary for debugging
            capture_exception(e)
            raise e
