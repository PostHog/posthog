from uuid import UUID

from django.db import transaction

from celery import shared_task

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.user import User

from products.data_modeling.backend.logic import view_column_refresh


@shared_task(ignore_result=True, autoretry_for=(ConcurrencyLimitExceeded,), retry_backoff=True, max_retries=3)
def refresh_downstream_view_columns(team_id: int, saved_query_id: str, user_id: int | None) -> None:
    with team_scope(team_id):
        team = Team.objects.get(pk=team_id)
        user = User.objects.filter(pk=user_id).first() if user_id is not None else None
        view_column_refresh.refresh_downstream_view_columns(team, saved_query_id, user)


def schedule_downstream_view_column_refresh(team_id: int, saved_query_id: UUID, user_id: int | None) -> None:
    """Refresh the stored columns of the views downstream of this one once the current transaction commits."""
    transaction.on_commit(
        lambda: refresh_downstream_view_columns.delay(team_id, str(saved_query_id), user_id), robust=True
    )
