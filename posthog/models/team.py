import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import pytz
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinLengthValidator
from django.db import models

from posthog.constants import AvailableFeature
from posthog.helpers.dashboard_templates import create_dashboard_from_template
from posthog.utils import GenericEmails

from .dashboard import Dashboard
from .utils import UUIDClassicModel, generate_random_token_project, sane_repr

if TYPE_CHECKING:
    from posthog.models.organization import OrganizationMembership
    from posthog.models.user import User

TEAM_CACHE: Dict[str, "Team"] = {}

TIMEZONES = [(tz, tz) for tz in pytz.common_timezones]

# TODO: DEPRECATED; delete when these attributes can be fully removed from `Team` model
DEPRECATED_ATTRS = (
    "plugins_opt_in",
    "opt_out_capture",
    "event_names",
    "event_names_with_usage",
    "event_properties",
    "event_properties_with_usage",
    "event_properties_numerical",
)


class TeamManager(models.Manager):
    def set_test_account_filters(self, organization: Optional[Any]) -> List:
        filters = [
            {
                "key": "$host",
                "operator": "is_not",
                "value": ["localhost:8000", "localhost:5000", "127.0.0.1:8000", "127.0.0.1:3000", "localhost:3000"],
            },
        ]
        if organization:
            example_emails = organization.members.only("email")
            generic_emails = GenericEmails()
            example_emails = [email.email for email in example_emails if not generic_emails.is_generic(email.email)]
            if len(example_emails) > 0:
                example_email = re.search(r"@[\w.]+", example_emails[0])
                if example_email:
                    return [
                        {"key": "email", "operator": "not_icontains", "value": example_email.group(), "type": "person"},
                    ] + filters
        return filters

    def create_with_data(self, user: Any = None, default_dashboards: bool = True, **kwargs) -> "Team":
        kwargs["test_account_filters"] = self.set_test_account_filters(kwargs.get("organization"))
        team = Team.objects.create(**kwargs)

        # Create default dashboards (skipped for demo projects)
        # TODO: Support multiple dashboard flavors based on #2822 personalization
        if default_dashboards:
            dashboard = Dashboard.objects.create(name="My App Dashboard", pinned=True, team=team)
            create_dashboard_from_template("DEFAULT_APP", dashboard)
        return team

    def create(self, *args, **kwargs) -> "Team":
        if kwargs.get("organization") is None and kwargs.get("organization_id") is None:
            raise ValueError("Creating organization-less projects is prohibited")
        return super().create(*args, **kwargs)

    def get_team_from_token(self, token: Optional[str]) -> Optional["Team"]:
        if not token:
            return None
        try:
            return Team.objects.defer(*DEPRECATED_ATTRS).get(api_token=token)
        except Team.DoesNotExist:
            return None


def get_default_data_attributes() -> Any:
    return ["data-attr"]


class Team(UUIDClassicModel):
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="teams", related_query_name="team"
    )
    api_token: models.CharField = models.CharField(
        max_length=200,
        unique=True,
        default=generate_random_token_project,
        validators=[MinLengthValidator(10, "Project's API token must be at least 10 characters long!")],
    )
    app_urls: ArrayField = ArrayField(models.CharField(max_length=200, null=True), default=list, blank=True)
    name: models.CharField = models.CharField(
        max_length=200, default="Default Project", validators=[MinLengthValidator(1, "Project must have a name!")],
    )
    slack_incoming_webhook: models.CharField = models.CharField(max_length=500, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    anonymize_ips: models.BooleanField = models.BooleanField(default=False)
    completed_snippet_onboarding: models.BooleanField = models.BooleanField(default=False)
    ingested_event: models.BooleanField = models.BooleanField(default=False)
    session_recording_opt_in: models.BooleanField = models.BooleanField(default=False)
    session_recording_retention_period_days: models.IntegerField = models.IntegerField(
        null=True, default=None, blank=True
    )
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    is_demo: models.BooleanField = models.BooleanField(default=False)
    access_control: models.BooleanField = models.BooleanField(default=False)
    test_account_filters: models.JSONField = models.JSONField(default=list)
    path_cleaning_filters: models.JSONField = models.JSONField(default=list, null=True, blank=True)
    timezone: models.CharField = models.CharField(max_length=240, choices=TIMEZONES, default="UTC")
    data_attributes: models.JSONField = models.JSONField(default=get_default_data_attributes)

    # DEPRECATED, DISUSED: plugins are enabled for everyone now
    plugins_opt_in: models.BooleanField = models.BooleanField(default=False)
    # DEPRECATED, DISUSED: replaced with env variable OPT_OUT_CAPTURE and User.anonymized_data
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)
    # DEPRECATED: in favor of `EventDefinition` model
    event_names: models.JSONField = models.JSONField(default=list)
    event_names_with_usage: models.JSONField = models.JSONField(default=list)
    # DEPRECATED: in favor of `PropertyDefinition` model
    event_properties: models.JSONField = models.JSONField(default=list)
    event_properties_with_usage: models.JSONField = models.JSONField(default=list)
    event_properties_numerical: models.JSONField = models.JSONField(default=list)

    objects: TeamManager = TeamManager()

    def get_effective_membership_level(self, user: "User") -> Optional["OrganizationMembership.Level"]:
        """Return an effective membership level.
        None returned if the user has no explicit membership and organization access is too low for implicit membership.
        """
        from posthog.models.organization import OrganizationMembership

        try:
            requesting_parent_membership: OrganizationMembership = OrganizationMembership.objects.select_related(
                "organization"
            ).get(organization_id=self.organization_id, user=user)
        except OrganizationMembership.DoesNotExist:
            return None
        if (
            not settings.EE_AVAILABLE
            or not requesting_parent_membership.organization.is_feature_available(
                AvailableFeature.PROJECT_BASED_PERMISSIONING
            )
            or not self.access_control
        ):
            return requesting_parent_membership.level
        from ee.models import ExplicitTeamMembership

        try:
            return (
                requesting_parent_membership.explicit_team_memberships.only("parent_membership", "level")
                .get(team=self)
                .effective_level
            )
        except ExplicitTeamMembership.DoesNotExist:
            # Only organizations admins and above get implicit project membership
            if requesting_parent_membership.level < OrganizationMembership.Level.ADMIN:
                return None
            return requesting_parent_membership.level

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return ", ".join(self.app_urls)
        return str(self.pk)

    __repr__ = sane_repr("uuid", "name", "api_token")
