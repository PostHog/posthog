from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models import Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.authz.backend.facade.synchronization import schedule_organization_sync, synchronization_enabled


@receiver(pre_save, sender=AccessControl)
@receiver(pre_save, sender=Role)
@receiver(pre_save, sender=RoleMembership)
@receiver(pre_delete, sender=AccessControl)
@receiver(pre_delete, sender=Role)
@receiver(pre_delete, sender=RoleMembership)
def remember_organization(
    sender: type[Model], instance: AccessControl | Role | RoleMembership, using: str, **kwargs: object
) -> None:
    if not synchronization_enabled():
        return
    field = (
        "team__organization_id"
        if isinstance(instance, AccessControl)
        else "role__organization_id"
        if isinstance(instance, RoleMembership)
        else "organization_id"
    )
    old_id = sender._default_manager.using(using).filter(pk=instance.pk).values_list(field, flat=True).first()
    instance.__dict__["_authz_old_organization_id"] = old_id


@receiver(post_save, sender=AccessControl)
@receiver(post_save, sender=Role)
@receiver(post_save, sender=RoleMembership)
@receiver(post_delete, sender=AccessControl)
@receiver(post_delete, sender=Role)
@receiver(post_delete, sender=RoleMembership)
def synchronize_access_control(
    sender: type[Model],
    instance: AccessControl | Role | RoleMembership,
    using: str,
    raw: bool = False,
    **kwargs: object,
) -> None:
    if raw or not synchronization_enabled():
        return
    if isinstance(instance, AccessControl):
        organization_id = (
            Team.objects.using(using).filter(id=instance.team_id).values_list("organization_id", flat=True).first()
        )
    elif isinstance(instance, RoleMembership):
        organization_id = (
            # Resolve the tenant from the lifecycle event's trusted role FK.
            # nosemgrep: idor-lookup-without-org
            Role.objects.using(using).filter(id=instance.role_id).values_list("organization_id", flat=True).first()
        )
    else:
        organization_id = instance.organization_id
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)
