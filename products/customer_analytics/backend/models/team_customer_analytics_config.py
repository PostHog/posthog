import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal
from posthog.rbac.decorators import field_access_control

from products.customer_analytics.backend.constants import (
    DEFAULT_ACTIVITY_EVENT,
    DEFAULT_OWNERSHIP_CLAIM_CLOCK_SKEW_TOLERANCE_SECONDS,
)

logger = logging.getLogger(__name__)


def default_account_track_rules() -> dict:
    return {
        "schema_version": 1,
        "version": 0,
        "enabled": False,
        "groups": [],
    }


class TeamCustomerAnalyticsConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    activity_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    signup_pageview_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    signup_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    subscription_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    payment_event = field_access_control(models.JSONField(default=dict), "project", "admin")
    account_group_type_index = field_access_control(models.IntegerField(null=True, blank=True), "project", "admin")
    account_track_rules = field_access_control(
        models.JSONField(default=default_account_track_rules), "project", "admin"
    )
    account_track_rules_enabled_at = models.DateTimeField(null=True, blank=True)
    # The relationship definitions that carry the account executive and customer success manager
    # roles. Binding names the role; each account's per-role control timestamp says whether the
    # role is managed there. RESTRICT keeps a bound definition, and the history under it, deletable
    # only after it is unbound, while still letting a team deletion cascade through both rows.
    ae_relationship_definition = field_access_control(
        models.ForeignKey(
            "customer_analytics.AccountRelationshipDefinition",
            on_delete=models.RESTRICT,
            null=True,
            blank=True,
            related_name="+",
        ),
        "project",
        "admin",
    )
    csm_relationship_definition = field_access_control(
        models.ForeignKey(
            "customer_analytics.AccountRelationshipDefinition",
            on_delete=models.RESTRICT,
            null=True,
            blank=True,
            related_name="+",
        ),
        "project",
        "admin",
    )
    ownership_claims_enabled = field_access_control(models.BooleanField(default=False), "project", "admin")
    # The warehouse view the claim reconciler reads Salesforce Task decisions from. The view maps the
    # Task's frozen fields onto the columns `logic/ownership_claims.py` documents, so Salesforce
    # field names stay out of this codebase.
    ownership_claim_saved_query = field_access_control(
        models.ForeignKey(
            "data_modeling.DataWarehouseSavedQuery",
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            related_name="+",
        ),
        "project",
        "admin",
    )
    # An automated claim is accepted only when its allocation time is later than the role fence by more
    # than this allowance, so a clock difference between the allocation source and this database cannot
    # make a stale decision look fresh.
    ownership_claim_clock_skew_tolerance_seconds = field_access_control(
        models.PositiveIntegerField(default=DEFAULT_OWNERSHIP_CLAIM_CLOCK_SKEW_TOLERANCE_SECONDS),
        "project",
        "admin",
    )

    def to_cache_key_dict(self) -> dict:
        return {
            "activity_event": self.activity_event,
            "signup_pageview_event": self.signup_pageview_event,
            "signup_event": self.signup_event,
            "subscription_event": self.subscription_event,
            "payment_event": self.payment_event,
        }


register_team_extension_signal(
    TeamCustomerAnalyticsConfig,
    defaults={"activity_event": DEFAULT_ACTIVITY_EVENT},
    logger=logger,
)
