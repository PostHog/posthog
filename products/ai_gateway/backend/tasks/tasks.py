"""
Celery tasks for ai_gateway.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin - only call facade methods.
"""

from celery import shared_task

from ..facade import api
from ..facade.contracts import DevTokenRefused

_GATEWAY_RETRY = {
    "autoretry_for": (DevTokenRefused,),
    "retry_backoff": 30,
    "retry_backoff_max": 600,
    "max_retries": 8,
}


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=70, **_GATEWAY_RETRY)
def revoke_dev_tokens_for_ineligible_owner(user_id: int) -> None:
    api.revoke_dev_tokens_for_ineligible_owner(user_id)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=70, **_GATEWAY_RETRY)
def revoke_dev_token_hashes(token_hashes: list[str]) -> None:
    api.revoke_dev_token_hashes(token_hashes)


@shared_task(ignore_result=True, soft_time_limit=600, time_limit=660)
def sweep_ineligible_dev_token_owners() -> None:
    api.sweep_ineligible_dev_token_owners()
