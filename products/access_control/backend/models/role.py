from collections.abc import Collection, Iterable
from typing import Any, cast
from uuid import UUID

from django.db import models, transaction
from django.db.models import F, Q

from posthog.models.organization import OrganizationMembership
from posthog.models.utils import UUIDTModel
from posthog.organization_caching import invalidate_organization_membership_access_caches

from products.access_control.backend.models.organization_resource_access import OrganizationResourceAccess


class RoleQuerySet(models.QuerySet["Role"]):
    def invalidate_organization_access(self, previous_members: Iterable[tuple[UUID, int | None]]) -> None:
        role_ids = tuple(self.values_list("pk", flat=True))
        previous = set(previous_members)
        model = self.model

        def invalidate_after_commit() -> None:
            members = previous.copy()
            try:
                # A concurrent membership insert may commit after the grant write but before this commit.
                members.update(model.objects.filter(pk__in=role_ids).values_list("organization_id", "role__user_id"))
            finally:
                invalidate_organization_membership_access_caches(
                    (organization_id, user_id) for organization_id, user_id in members if user_id is not None
                )

        transaction.on_commit(invalidate_after_commit, robust=True)

    # django-stubs rebinds QuerySet subclasses to its own TypeVar instead of the declared model.
    def bulk_create(  # type: ignore[override]
        self,
        objs: Iterable["Role"],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list["Role"]:
        if update_conflicts:
            raise ValueError("Use update or bulk_update to change existing role grants.")
        return cast(
            list[Role],
            super().bulk_create(
                cast(Iterable[Any], objs), batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
            ),
        )

    def update(self, **kwargs: Any) -> int:
        if not {"organization_access_level", "organization", "organization_id"}.intersection(kwargs):
            return super().update(**kwargs)
        from products.authorization.backend.facade import (
            api as authorization,  # noqa: PLC0415 - breaks a model import cycle
        )

        with transaction.atomic():
            ids = list(self.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
            affected = self.model.objects.filter(pk__in=ids)
            members = set(affected.values_list("organization_id", "role__user_id"))
            updated = super(RoleQuerySet, affected).update(**kwargs)
            authorization.invalidate_session()
            affected.invalidate_organization_access(members)
            return updated


class Role(UUIDTModel):
    objects = RoleQuerySet.as_manager()

    class OrganizationAccessLevel(models.IntegerChoices):
        ADMIN = OrganizationMembership.Level.ADMIN, "administrator"

    class Meta:
        app_label = "ee"
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_role_name"),
            models.CheckConstraint(
                condition=Q(organization_access_level__isnull=True)
                | Q(organization_access_level=OrganizationMembership.Level.ADMIN),
                name="role_org_access_level_admin_or_null",
            ),
        ]

    name = models.CharField(max_length=200)
    organization_access_level = models.SmallIntegerField(
        null=True,
        blank=True,
        choices=OrganizationAccessLevel.choices,
    )
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="roles",
        related_query_name="role",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="roles",
        related_query_name="role",
        null=True,
    )

    # DEPRECATED - do not use
    feature_flags_access_level = models.PositiveSmallIntegerField(
        default=OrganizationResourceAccess.AccessLevel.CAN_ALWAYS_EDIT,
        choices=OrganizationResourceAccess.AccessLevel,
    )

    members = models.ManyToManyField(
        "posthog.User",
        through="ee.RoleMembership",
    )


class RoleMembershipQuerySet(models.QuerySet["RoleMembership"]):
    def update(self, **kwargs: Any) -> int:
        from products.authorization.backend.facade import (
            api as authorization,  # noqa: PLC0415 - breaks a model import cycle
        )

        with transaction.atomic():
            ids = list(self.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
            affected = self.model.objects.filter(pk__in=ids)
            members = set(affected.values_list("role__organization_id", "user_id"))
            updated = super(RoleMembershipQuerySet, affected).update(**kwargs)
            authorization.invalidate_session()
            members.update(affected.values_list("role__organization_id", "user_id"))
            invalidate_organization_membership_access_caches(members)
            return updated

    # django-stubs rebinds QuerySet subclasses to its own TypeVar instead of the declared model.
    def bulk_create(  # type: ignore[override]
        self,
        objs: Iterable["RoleMembership"],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list["RoleMembership"]:
        if update_conflicts:
            raise ValueError("Use update or bulk_update to change existing role memberships.")
        from products.authorization.backend.facade import (
            api as authorization,  # noqa: PLC0415 - breaks a model import cycle
        )

        with transaction.atomic():
            created = cast(
                list[RoleMembership],
                super().bulk_create(
                    cast(Iterable[Any], objs),
                    batch_size,
                    ignore_conflicts,
                    update_conflicts,
                    update_fields,
                    unique_fields,
                ),
            )
            authorization.invalidate_session()
            role_ids = {obj.role_id for obj in created}
            organizations = dict(Role.objects.filter(pk__in=role_ids).values_list("pk", "organization_id"))
            invalidate_organization_membership_access_caches(
                (organizations[obj.role_id], obj.user_id) for obj in created
            )
            return created

    def valid_for_authorization(self) -> "RoleMembershipQuerySet":
        return self.filter(
            Q(organization_member__isnull=True) | Q(organization_member__organization_id=F("role__organization_id"))
        )


class RoleMembership(UUIDTModel):
    objects = RoleMembershipQuerySet.as_manager()

    class Meta:
        app_label = "ee"
        constraints = [models.UniqueConstraint(fields=["role", "user"], name="unique_user_and_role")]

    role = models.ForeignKey(
        "Role",
        on_delete=models.CASCADE,
        related_name="roles",
        related_query_name="role",
    )
    # TODO: Eventually remove this as we only need the organization membership
    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="role_memberships",
        related_query_name="role_membership",
    )

    organization_member = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="role_memberships",
        related_query_name="role_membership",
        null=True,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
