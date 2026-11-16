"""
Celery tasks for ai_gateway.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin - only call facade methods.
"""

from celery import shared_task

from ..facade import api
from ..facade.contracts import DevTokenRefused


@shared_task(
    ignore_result=True,
    autoretry_for=(DevTokenRefused,),
    retry_backoff=30,
    retry_backoff_max=600,
    max_retries=8,
    soft_time_limit=60,
    time_limit=70,
)
def revoke_dev_tokens_for_ineligible_owner(user_id: int) -> None:
    api.revoke_dev_tokens_for_ineligible_owner(user_id)
