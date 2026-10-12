from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from posthog.models import Team
from posthog.settings import EE_AVAILABLE

from products.authz.backend.facade.synchronization import schedule_organization_sync, synchronization_enabled
from products.dashboards.backend.models.dashboard import Dashboard

if TYPE_CHECKING:
    from ee.models.dashboard_privilege import DashboardPrivilege


@receiver(pre_save, sender=Dashboard)
@receiver(pre_delete, sender=Dashboard)
def remember_organization(sender: type[Dashboard], instance: Dashboard, using: str, **kwargs: object) -> None:
    if synchronization_enabled():
        # Read the stored tenant before a save can move the dashboard to a different one.
        # nosemgrep: idor-lookup-without-team
        old_id = (
            Dashboard.objects_including_soft_deleted.using(using)
            .filter(pk=instance.pk)
            .values_list("team__organization_id", flat=True)
            .first()
        )
        instance.__dict__["_authz_old_organization_id"] = old_id


@receiver(post_save, sender=Dashboard)
@receiver(post_delete, sender=Dashboard)
def synchronize_dashboard(
    sender: type[Dashboard], instance: Dashboard, using: str, raw: bool = False, **kwargs: object
) -> None:
    if raw or not synchronization_enabled():
        return
    organization_id = (
        Team.objects.using(using).filter(id=instance.team_id).values_list("organization_id", flat=True).first()
    )
    for id in {organization_id, instance.__dict__.get("_authz_old_organization_id")}:
        if id is not None:
            schedule_organization_sync(id, using=using)


def synchronize_privilege(
    sender: type[DashboardPrivilege], instance: DashboardPrivilege, using: str, raw: bool = False, **kwargs: object
) -> None:
    if raw or not synchronization_enabled():
        return
    # The privilege contains a dashboard id, not a trusted tenant id.
    # nosemgrep: idor-lookup-without-team
    organization_id = (
        Dashboard.objects_including_soft_deleted.using(using)
        .filter(id=instance.dashboard_id)
        .values_list("team__organization_id", flat=True)
        .first()
    )
    if organization_id is not None:
        schedule_organization_sync(organization_id, using=using)


if EE_AVAILABLE:
    post_save.connect(synchronize_privilege, sender="ee.DashboardPrivilege")
    post_delete.connect(synchronize_privilege, sender="ee.DashboardPrivilege")
