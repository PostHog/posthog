from typing import TYPE_CHECKING, cast

from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models import Organization, OrganizationMembership, Team

if TYPE_CHECKING:
    from posthog.models import SharingConfiguration

from products.authz.backend.facade.synchronization import (
    invalidate_authorization_session,
    schedule_organization_sync,
    synchronization_enabled,
)


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


@receiver(pre_save, sender="posthog.SharingConfiguration")
@receiver(pre_delete, sender="posthog.SharingConfiguration")
@receiver(pre_save, sender="notebooks.Notebook")
@receiver(pre_delete, sender="notebooks.Notebook")
@receiver(pre_save, sender="posthog.SessionRecording")
@receiver(pre_delete, sender="posthog.SessionRecording")
def remember_shared_object_organization(sender: type[Model], instance: Model, using: str, **kwargs: object) -> None:
    if synchronization_enabled():
        # A tenant move must revoke the old organization's share relationships as well.
        instance.__dict__["_authz_old_organization_id"] = (
            sender._default_manager.using(using)
            .filter(pk=instance.pk)
            .values_list("team__organization_id", flat=True)
            .first()
        )


@receiver(post_save, sender="posthog.SharingConfiguration")
@receiver(post_delete, sender="posthog.SharingConfiguration")
@receiver(post_save, sender="notebooks.Notebook")
@receiver(post_delete, sender="notebooks.Notebook")
@receiver(post_save, sender="posthog.SessionRecording")
@receiver(post_delete, sender="posthog.SessionRecording")
def synchronize_shared_object(
    sender: type[Model], instance: Model, using: str, raw: bool = False, **kwargs: object
) -> None:
    invalidate_authorization_session()
    if raw or not synchronization_enabled():
        return
    organization_id = (
        Team.objects.using(using)
        .filter(id=cast("SharingConfiguration", instance).team_id)
        .values_list("organization_id", flat=True)
        .first()
    )
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)


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
    invalidate_authorization_session()
    if raw or not synchronization_enabled():
        return
    organization_id = instance.pk if isinstance(instance, Organization) else instance.organization_id
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)
