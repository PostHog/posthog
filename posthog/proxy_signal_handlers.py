from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models import Organization, ProxyRecord


@receiver(post_save, sender=Organization)
def reconcile_proxies_on_organization_active_change(
    sender: type[Organization], instance: Organization, created: bool, raw: bool = False, **kwargs: object
) -> None:
    if raw or created or not instance._is_active_changed:
        return

    organization_id = instance.pk

    def enqueue_reconciliation() -> None:
        from posthog.tasks.proxy import enqueue_proxy_reconciliation  # noqa: PLC0415

        for proxy_record_id in ProxyRecord.objects.filter(organization_id=organization_id).values_list("id", flat=True):
            enqueue_proxy_reconciliation(str(organization_id), str(proxy_record_id))

    transaction.on_commit(enqueue_reconciliation, robust=True)
