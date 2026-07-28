from enum import Enum
from typing import cast

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
    slack_channel_id: str | None = None
    usage_dashboard_link: str | None = None

    @classmethod
    def from_input(cls, data: "dict | AccountProperties") -> "AccountProperties":
        if isinstance(data, AccountProperties):
            data = data.model_dump(mode="json", exclude_unset=True)
        return cls.model_validate(data)


class _Unset(Enum):
    UNSET = "unset"


_UNSET = _Unset.UNSET


class AccountManager(TeamScopedManager["Account"]):
    def update_account(
        self,
        account: "Account",
        *,
        name: str | _Unset = _UNSET,
        external_id: str | None | _Unset = _UNSET,
        properties: "dict | AccountProperties | _Unset" = _UNSET,
    ) -> "Account":
        update_fields: list[str] = []
        if name is not _UNSET:
            account.name = cap_to_field_length("name", name)
            update_fields.append("name")
        if external_id is not _UNSET:
            account.external_id = cap_to_field_length("external_id", external_id) if external_id is not None else None
            update_fields.append("external_id")
        if properties is not _UNSET:
            account._properties = AccountProperties.from_input(properties).model_dump(mode="json", exclude_unset=True)
            update_fields.append("_properties")
        if update_fields:
            account.save(update_fields=update_fields)
        return account


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


def cap_to_field_length(field_name: str, value: str) -> str:
    max_length = cast(models.CharField, Account._meta.get_field(field_name)).max_length
    return value[:max_length]


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
