from typing import Dict, Optional

import posthoganalytics
from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.utils import timezone

from posthog.constants import TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR, TRENDS_TABLE
from posthog.helpers.dashboard_templates import create_dashboard_from_template

from .dashboard import Dashboard
from .dashboard_item import DashboardItem
from .utils import UUIDT, generate_random_token, sane_repr

TEAM_CACHE: Dict[str, "Team"] = {}


class TeamManager(models.Manager):
    def create_with_data(self, user=None, **kwargs) -> "Team":
        team = Team.objects.create(**kwargs)

        # Create default dashboard
        if user and posthoganalytics.feature_enabled("1694-dashboards", user.distinct_id):
            # Create app template dashboard if feature flag is active
            dashboard = Dashboard.objects.create(name="My App Dashboard", pinned=True, team=team,)
            create_dashboard_from_template("DEFAULT_APP", dashboard)
        else:
            # DEPRECATED: Will be retired in favor of dashboard_templates.py
            dashboard = Dashboard.objects.create(
                name="Default", pinned=True, team=team, share_token=generate_random_token()
            )

            DashboardItem.objects.create(
                team=team,
                dashboard=dashboard,
                name="Pageviews this week",
                filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}]},
                last_refresh=timezone.now(),
            )
            DashboardItem.objects.create(
                team=team,
                dashboard=dashboard,
                name="Most popular browsers this week",
                filters={
                    TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}],
                    "display": TRENDS_TABLE,
                    "breakdown": "$browser",
                },
                last_refresh=timezone.now(),
            )
            DashboardItem.objects.create(
                team=team,
                dashboard=dashboard,
                name="Daily Active Users",
                filters={
                    TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}]
                },
                last_refresh=timezone.now(),
            )

        return team

    def create(self, *args, **kwargs) -> "Team":
        if kwargs.get("organization") is None and kwargs.get("organization_id") is None:
            raise ValueError("Creating organization-less projects is prohibited")
        return super().create(*args, **kwargs)

    def get_team_from_token(self, token: Optional[str]) -> Optional["Team"]:
        if not token:
            return None
        try:
            return Team.objects.get(api_token=token)
        except Team.DoesNotExist:
            return None


class Team(models.Model):
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="teams", related_query_name="team", null=True
    )
    api_token: models.CharField = models.CharField(
        max_length=200, null=True, unique=True, default=generate_random_token
    )
    app_urls: ArrayField = ArrayField(models.CharField(max_length=200, null=True, blank=True), default=list)
    name: models.CharField = models.CharField(max_length=200, null=True, default="Default Project")
    slack_incoming_webhook: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    event_names: JSONField = JSONField(default=list)
    event_names_with_usage: JSONField = JSONField(default=list)
    event_properties: JSONField = JSONField(default=list)
    event_properties_with_usage: JSONField = JSONField(default=list)
    event_properties_numerical: JSONField = JSONField(default=list)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    anonymize_ips: models.BooleanField = models.BooleanField(default=False)
    completed_snippet_onboarding: models.BooleanField = models.BooleanField(default=False)
    ingested_event: models.BooleanField = models.BooleanField(default=False)
    uuid: models.UUIDField = models.UUIDField(default=UUIDT, editable=False, unique=True)
    session_recording_opt_in: models.BooleanField = models.BooleanField(default=False)
    session_recording_retention_period_days: models.IntegerField = models.IntegerField(null=True, default=None)

    plugins_opt_in: models.BooleanField = models.BooleanField(default=False)

    # DEPRECATED: replaced with env variable OPT_OUT_CAPTURE and User field anonymized_data
    # However, we still honor teams that have set this previously
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)

    # DEPRECATED: with organizations, all users belonging to the organization get access to all its teams right away
    # This may be brought back into use with a more robust approach (and some constraint checks)
    users: models.ManyToManyField = models.ManyToManyField(
        "User", blank=True, related_name="teams_deprecated_relationship"
    )
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    is_demo: models.BooleanField = models.BooleanField(default=False)

    objects = TeamManager()

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return ", ".join(self.app_urls)
        return str(self.pk)

    __repr__ = sane_repr("uuid", "name", "api_token")
