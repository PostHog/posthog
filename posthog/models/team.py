import hashlib
import uuid as uuidlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.utils import timezone

from posthog.constants import TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR

from .action import Action
from .action_step import ActionStep
from .dashboard import Dashboard
from .dashboard_item import DashboardItem
from .personal_api_key import PersonalAPIKey
from .utils import generate_random_token

TEAM_CACHE: Dict[str, "Team"] = {}


class TeamManager(models.Manager):
    def create_with_data(self, **kwargs) -> "Team":
        team = Team.objects.create(**kwargs)

        action = Action.objects.create(team=team, name="Pageviews")
        ActionStep.objects.create(action=action, event="$pageview")

        dashboard = Dashboard.objects.create(
            name="Default", pinned=True, team=team, share_token=generate_random_token()
        )

        DashboardItem.objects.create(
            team=team,
            dashboard=dashboard,
            name="Pageviews this week",
            type=TRENDS_LINEAR,
            filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS}]},
            last_refresh=timezone.now(),
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
            last_refresh=timezone.now(),
        )
        DashboardItem.objects.create(
            team=team,
            dashboard=dashboard,
            name="Daily Active Users",
            type=TRENDS_LINEAR,
            filters={TREND_FILTER_TYPE_EVENTS: [{"id": "$pageview", "math": "dau", "type": TREND_FILTER_TYPE_EVENTS}]},
            last_refresh=timezone.now(),
        )
        return team

    def get_cached_from_token(self, token: str, is_personal_api_key: bool = False) -> Optional["Team"]:
        team_from_cache = TEAM_CACHE.get(token)
        if team_from_cache:
            return team_from_cache
        if not is_personal_api_key:
            try:
                team = Team.objects.get(api_token=token)
            except Team.DoesNotExist:
                return None
        else:
            try:
                personal_api_key = (
                    PersonalAPIKey.objects.select_related("user")
                    .select_related("team")
                    .filter(user__is_active=True)
                    .get(value=token)
                )
            except PersonalAPIKey.DoesNotExist:
                return None
            else:
                team = personal_api_key.team
                personal_api_key.last_used_at = timezone.now()
                personal_api_key.save()
        TEAM_CACHE[token] = team
        return team


class Team(models.Model):
    organization: models.ForeignKey = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="teams", related_query_name="team", null=True
    )
    api_token: models.CharField = models.CharField(
        max_length=200, null=True, unique=True, default=generate_random_token
    )
    app_urls: ArrayField = ArrayField(models.CharField(max_length=200, null=True, blank=True), default=list)
    name: models.CharField = models.CharField(max_length=200, null=True, default="Default")
    slack_incoming_webhook: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    event_names: JSONField = JSONField(default=list)
    event_properties: JSONField = JSONField(default=list)
    event_properties_numerical: JSONField = JSONField(default=list)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    anonymize_ips: models.BooleanField = models.BooleanField(default=False)
    completed_snippet_onboarding: models.BooleanField = models.BooleanField(default=False)
    ingested_event: models.BooleanField = models.BooleanField(default=False)
    uuid: models.UUIDField = models.UUIDField(default=uuidlib.uuid4, editable=False, unique=True)

    # DEPRECATED: replaced with env variable OPT_OUT_CAPTURE and User field anonymized_data
    # However, we still honor teams that have set this previously
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)

    # DEPRECATED: with organizations, all users belonging to the organization get access to all its teams right away
    # This may be brought back into use with a more robust approach (and some constraint checks)
    users: models.ManyToManyField = models.ManyToManyField(
        "User", blank=True, related_name="teams_deprecated_relationship"
    )
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)

    objects = TeamManager()

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return ", ".join(self.app_urls)
        return str(self.pk)

    @property
    def deterministic_derived_uuid(self) -> str:
        return uuidlib.UUID(hashlib.md5(self.id.to_bytes(16, "big")).hexdigest())
