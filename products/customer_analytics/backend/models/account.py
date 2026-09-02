from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import JSONField, Q
from django.db.models.signals import pre_save
from django.dispatch import receiver

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.customer_analytics.backend.domain import parse_company_domain
from products.customer_analytics.backend.models.account_channel_summary import SlackSummaryCadence

# Role assignments moved to the relationship tables. Stored rows may carry these keys until
# `backfill_account_relationships` has run in the environment (see COMPROMISES.md).
RETIRED_ROLE_KEYS = ("csm", "account_executive", "account_owner")


class AccountProperties(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website_domain: str | None = None
    # Email domains owned by this account's company, used to match inbound
    # touchpoints (calendar attendees, email senders) that don't resolve to a
    # known person. Personal/free domains don't belong here.
    email_domains: list[str] = []
    # Individual addresses pinned to this account, checked before the domain
    # fallback. For contacts on personal/free domains a domain rule can't cover.
    known_emails: list[str] = []

    @field_validator("website_domain")
    @classmethod
    def normalize_website_domain(cls, raw_domain: str | None, info: ValidationInfo) -> str | None:
        if not info.context or not info.context.get("normalize_website_domain"):
            return raw_domain
        if raw_domain is None or not raw_domain.strip():
            return None
        domain = parse_company_domain(raw_domain)
        if domain is None:
            raise ValueError("website_domain must be a company hostname")
        return domain

    @field_validator("email_domains")
    @classmethod
    def normalize_email_domains(cls, domains: list[str]) -> list[str]:
        normalized = (domain.strip().lower().removeprefix("@") for domain in domains)
        return list(dict.fromkeys(domain for domain in normalized if domain))

    @field_validator("known_emails")
    @classmethod
    def normalize_known_emails(cls, emails: list[str]) -> list[str]:
        normalized = (email.strip().lower() for email in emails)
        return list(dict.fromkeys(email for email in normalized if email))

    # External connections
    stripe_customer_id: str | None = None
    hubspot_deal_id: str | None = None
    billing_id: str | None = None
    sfdc_id: str | None = None
    zendesk_id: str | None = None
    slack_channel_id: str | None = None
    usage_dashboard_link: str | None = None
    metabase_link: str | None = None

    @classmethod
    def from_input(cls, data: "dict | AccountProperties") -> "AccountProperties":
        if isinstance(data, AccountProperties):
            data = data.model_dump(mode="json", exclude_unset=True)
        return cls.model_validate(data, context={"normalize_website_domain": True})


class Account(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    external_id = models.CharField(max_length=400, null=True, blank=True)
    name = models.CharField(max_length=400)
    churned_at = models.DateTimeField(null=True, blank=True)
    ignored_at = models.DateTimeField(null=True, blank=True)
    _properties = JSONField(default=dict, db_column="properties")
    # NULL = periodic Slack channel summaries off for this account.
    slack_summary_cadence = models.CharField(max_length=10, choices=SlackSummaryCadence.choices, null=True, blank=True)

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
        stored = self._properties or {}
        return AccountProperties.model_validate({k: v for k, v in stored.items() if k not in RETIRED_ROLE_KEYS})

    @properties.setter
    def properties(self, value: "dict | AccountProperties") -> None:
        validated = AccountProperties.from_input(value)
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
