from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.utils import UUIDModel

MAX_IP_RESTRICTIONS = 100


class OrganizationIPRestrictions(UUIDModel):
    """Management-access policy read by middleware, bearer authenticators, and settings.

    The management API gates configuration by entitlement; enforcement always honors saved policies.
    """

    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="ip_restrictions_config",
        # The FK constraint would lock the hot organization table during migration; the ORM
        # cascade still removes this row when the organization is deleted.
        db_constraint=False,
    )
    ip_restrictions = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
        help_text="IP addresses and CIDR blocks allowed to access this organization.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text="When False, the allowlist is kept but not enforced.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


@receiver([post_save, post_delete], sender=OrganizationIPRestrictions)
def _invalidate_organization_ip_restrictions_cache(sender, instance: OrganizationIPRestrictions, **kwargs) -> None:
    from posthog.ip_restrictions import invalidate_ip_restrictions_for_organization

    organization_id = instance.organization_id

    # Invalidate again after commit so concurrent readers cannot retain pre-commit policies.
    invalidate_ip_restrictions_for_organization(organization_id)
    transaction.on_commit(lambda: invalidate_ip_restrictions_for_organization(organization_id))


@receiver([post_save, post_delete], sender="posthog.OrganizationMembership")
def _invalidate_membership_ip_restrictions_cache(sender, instance, **kwargs) -> None:
    from posthog.ip_restrictions import invalidate_ip_restrictions_for_user

    user_id = getattr(instance, "user_id", None)
    if user_id is not None:
        invalidate_ip_restrictions_for_user(user_id)
        transaction.on_commit(lambda: invalidate_ip_restrictions_for_user(user_id))
