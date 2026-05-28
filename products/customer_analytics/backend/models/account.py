from typing import Any

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import JSONField, Q
from django.db.models.signals import pre_save
from django.dispatch import receiver

from pydantic import BaseModel, ConfigDict

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class AccountAssignment(BaseModel):
    id: int
    email: str


class AccountProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Key roles
    csm: AccountAssignment | None = None
    account_executive: AccountAssignment | None = None
    account_owner: AccountAssignment | None = None

    # External connections
    stripe_customer_id: str | None = None
    hubspot_deal_id: str | None = None
    billing_id: str | None = None
    sfdc_id: str | None = None
    zendesk_id: str | None = None


class AccountManager(TeamScopedManager["Account"]):
    def create(
        self,
        *,
        properties: "dict | AccountProperties | None" = None,
        **kwargs: Any,
    ) -> "Account":
        if properties is not None:
            validated = (
                properties
                if isinstance(properties, AccountProperties)
                else AccountProperties.model_validate(properties)
            )
            kwargs["_properties"] = validated.model_dump(mode="json")
        return super().create(**kwargs)


class Account(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    external_id = models.CharField(max_length=400, null=True, blank=True)
    name = models.CharField(max_length=400)
    _properties = JSONField(default=dict, db_column="properties")

    objects = AccountManager()  # type: ignore[assignment, misc]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "external_id"],
                name="unique_account_external_id_per_team",
                condition=Q(external_id__isnull=False),
            ),
        ]

    @property
    def properties(self) -> AccountProperties:
        return AccountProperties.model_validate(self._properties or {})

    @properties.setter
    def properties(self, value: "dict | AccountProperties") -> None:
        validated = value if isinstance(value, AccountProperties) else AccountProperties.model_validate(value)
        self._properties = validated.model_dump(mode="json")


@receiver(pre_save, sender="customer_analytics.TeamCustomerAnalyticsConfig")
def _enforce_account_group_type_index_drift_policy(sender, instance, **kwargs) -> None:
    if instance.pk is None:
        return

    update_fields = kwargs.get("update_fields")
    if update_fields and "account_group_type_index" not in update_fields:
        return

    previous = sender.objects.filter(pk=instance.pk).values_list("account_group_type_index", flat=True).first()
    if previous is None or previous == instance.account_group_type_index:
        return

    AccountModel = apps.get_model("customer_analytics", "Account")
    if AccountModel.objects.unscoped().filter(team_id=instance.team_id).exists():
        raise ValidationError("Cannot change account_group_type_index once accounts exist for this team")
