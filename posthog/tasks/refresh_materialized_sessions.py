from celery import shared_task
import logging
from django.db import connection

logger = logging.getLogger(__name__)

@shared_task
def refresh_materialized_sessions(team_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute('REFRESH MATERIALIZED VIEW sessions_team_{}'.format(team_id))