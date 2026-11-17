from typing import Any

from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models.organization import OrganizationMembership
from posthog.organization_caching import invalidate_organization_membership_access_caches

from products.access_control.backend.models.role import Role, RoleMembership


@receiver(pre_save, sender=Role)
def remember_previous_role_grants(sender: type[Role], instance: Role, **kwargs: Any) -> None:
    instance._previous_grant_members = list(  # type: ignore[attr-defined]
        Role.objects.filter(pk=instance.pk).values_list("organization_id", "role__user_id")
    )


@receiver(post_save, sender=Role)
@receiver(pre_delete, sender=Role)
def invalidate_role_grants(sender: type[Role], instance: Role, **kwargs: Any) -> None:
    members = set(getattr(instance, "_previous_grant_members", []))
    members.update((instance.organization_id, user_id) for user_id in instance.roles.values_list("user_id", flat=True))
    Role.objects.filter(pk=instance.pk).invalidate_organization_access(members)


@receiver(pre_save, sender=RoleMembership)
@receiver(pre_delete, sender=RoleMembership)
def remember_previous_role_membership(sender: type[RoleMembership], instance: RoleMembership, **kwargs: Any) -> None:
    instance._previous_grant_members = list(  # type: ignore[attr-defined]
        RoleMembership.objects.filter(pk=instance.pk).values_list("role__organization_id", "user_id")
    )


@receiver(post_save, sender=RoleMembership)
def invalidate_role_membership(sender: type[RoleMembership], instance: RoleMembership, **kwargs: Any) -> None:
    members = set(getattr(instance, "_previous_grant_members", []))
    members.add((instance.role.organization_id, instance.user_id))
    invalidate_organization_membership_access_caches(members)


@receiver(post_delete, sender=RoleMembership)
def invalidate_deleted_role_membership(sender: type[RoleMembership], instance: RoleMembership, **kwargs: Any) -> None:
    invalidate_organization_membership_access_caches(getattr(instance, "_previous_grant_members", []))


@receiver(pre_delete, sender=OrganizationMembership)
def remove_legacy_role_memberships(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any
) -> None:
    # NULL links have no membership FK to cascade, so remove them before a later rejoin can inherit them.
    RoleMembership.objects.filter(
        user_id=instance.user_id, role__organization_id=instance.organization_id, organization_member__isnull=True
    ).delete()
