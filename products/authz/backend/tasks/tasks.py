from uuid import UUID

from celery import shared_task


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=300, retry_kwargs={"max_retries": 10})
def synchronize_organization(organization_id: str) -> None:
    from products.authz.backend.facade import api  # noqa: PLC0415 -- keep projection and SDK imports off Django setup

    api.synchronize_organization(UUID(organization_id))
