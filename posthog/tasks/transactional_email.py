from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.transactional_email import TransactionalEmailRetryableError, send_transactional_email


@shared_task(
    ignore_result=True,
    autoretry_for=(TransactionalEmailRetryableError,),
    retry_backoff=True,
    max_retries=5,
    # Redelivery after worker loss could duplicate a send the API already accepted.
    acks_late=False,
)
@skip_team_scope_audit
def send_transactional_email_task(
    template_id: str,
    *,
    to: str,
    distinct_id: str | None = None,
    message_data: dict[str, object] | None = None,
) -> str:
    return send_transactional_email(template_id, to=to, distinct_id=distinct_id, message_data=message_data)
