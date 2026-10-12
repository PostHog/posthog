from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models import Organization, OrganizationMembership, Team

from products.authz.backend.facade.synchronization import schedule_organization_sync, synchronization_enabled


@receiver(pre_save, sender=Team)
@receiver(pre_save, sender=OrganizationMembership)
@receiver(pre_delete, sender=Team)
@receiver(pre_delete, sender=OrganizationMembership)
def remember_organization(
    sender: type[Model], instance: Team | OrganizationMembership, using: str, **kwargs: object
) -> None:
    if synchronization_enabled():
        instance.__dict__["_authz_old_organization_id"] = (
            sender._default_manager.using(using)
            .filter(pk=instance.pk)
            .values_list("organization_id", flat=True)
            .first()
        )


@receiver(post_save, sender=Organization)
@receiver(post_delete, sender=Organization)
@receiver(post_save, sender=Team)
@receiver(post_delete, sender=Team)
@receiver(post_save, sender=OrganizationMembership)
@receiver(post_delete, sender=OrganizationMembership)
def synchronize_membership(
    sender: type[Model],
    instance: Organization | Team | OrganizationMembership,
    using: str,
    raw: bool = False,
    **kwargs: object,
) -> None:
    if raw or not synchronization_enabled():
        return
    organization_id = instance.pk if isinstance(instance, Organization) else instance.organization_id
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)
