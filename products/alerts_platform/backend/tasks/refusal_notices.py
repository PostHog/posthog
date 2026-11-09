from celery import shared_task

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.delivery.refusal_notices import RefusalNotice, send_notice


@shared_task(ignore_result=True)
def send_refusal_notice(
    *,
    team_id: int,
    key: str,
    configuration_id: str,
    source: str,
    alert_name: str,
    alert_url: str,
    refusal: str,
) -> None:
    with team_scope(team_id):
        send_notice(
            RefusalNotice(
                team_id=team_id,
                key=key,
                configuration_id=configuration_id,
                source=source,
                alert_name=alert_name,
                alert_url=alert_url,
                refusal=refusal,
            )
        )
