from django.db import models
from django.contrib.postgres.fields import JSONField, ArrayField
from .action import Action
from .action_step import ActionStep
from .dashboard import Dashboard
from .dashboard_item import DashboardItem
from .user import User
from posthog.constants import TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from typing import Optional, List, Dict
from datetime import datetime
import secrets

TEAM_CACHE: Dict[str, "Team"] = {}


class TeamManager(models.Manager):
    def create_with_data(self, users: Optional[List[User]], **kwargs):
        kwargs["api_token"] = kwargs.get("api_token", secrets.token_urlsafe(32))
        kwargs["signup_token"] = kwargs.get("signup_token", secrets.token_urlsafe(22))
        team = Team.objects.create(**kwargs)
        if users:
            team.users.set(users)

        action = Action.objects.create(team=team, name="Pageviews")
        ActionStep.objects.create(action=action, event="$pageview")

        dashboard = Dashboard.objects.create(
            name="Default", pinned=True, team=team, share_token=secrets.token_urlsafe(22)
        )

        DashboardItem.objects.create(
            team=team,
            dashboard=dashboard,
            name="Pageviews this week",
            type=TRENDS_LINEAR,
            filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}]},
            last_refresh=datetime.now(),
        )
        DashboardItem.objects.create(
            team=team,
            dashboard=dashboard,
            name="Most popular browsers this week",
            type="ActionsTable",
            filters={
                TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}],
                "display": "ActionsTable",
                "breakdown": "$browser",
            },
            last_refresh=datetime.now(),
        )
        DashboardItem.objects.create(
            team=team,
            dashboard=dashboard,
            name="Daily Active Users",
            type=TRENDS_LINEAR,
            filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}]},
            last_refresh=datetime.now(),
        )
        return team

    def get_cached_from_token(self, token: str) -> "Team":
        if TEAM_CACHE.get(token):
            return TEAM_CACHE[token]
        team = Team.objects.get(api_token=token)
        TEAM_CACHE[token] = team
        return team


class Team(models.Model):
    users: models.ManyToManyField = models.ManyToManyField(User, blank=True)
    api_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    app_urls: ArrayField = ArrayField(models.CharField(max_length=200, null=True, blank=True), default=list)
    name: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    slack_incoming_webhook: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    event_names: JSONField = JSONField(default=list)
    event_properties: JSONField = JSONField(default=list)
    event_properties_numerical: JSONField = JSONField(default=list)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    anonymize_ips: models.BooleanField = models.BooleanField(default=False)
    completed_snippet_onboarding: models.BooleanField = models.BooleanField(default=False)

    # DEPRECATED: this field is deprecated in favour of OPT_OUT_CAPTURE env variable and anonymized data
    # However, we still honor teams that have set this previously
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)

    objects = TeamManager()

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return self.app_urls.join(", ")
        return str(self.pk)
