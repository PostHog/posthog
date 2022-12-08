from celery import shared_task
from django.db import transaction

from posthog.demo.matrix.manager import MatrixManager
from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix
from posthog.models.team.team import Team
from posthog.models.user import User


@shared_task(ignore_result=True, bind=True)
def create_data_for_demo_team(self, team_id: int, user_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    user = User.objects.get(pk=user_id)
    if team and user:
        with transaction.atomic():
            MatrixManager(HedgeboxMatrix(), use_pre_save=True).run_on_team(team, user)
