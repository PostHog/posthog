import re
from functools import lru_cache
from typing import Any, List, Optional

import posthoganalytics
import pytz
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models.signals import post_delete, post_save

from posthog.clickhouse.query_tagging import tag_queries
from posthog.cloud_utils import is_cloud
from posthog.helpers.dashboard_templates import create_dashboard_from_template
from posthog.models.dashboard import Dashboard
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.instance_setting import get_instance_setting
from posthog.models.signals import mutable_receiver
from posthog.models.team.util import actor_on_events_ready
from posthog.models.utils import UUIDClassicModel, generate_random_token_project, sane_repr
from posthog.settings.utils import get_list
from posthog.utils import GenericEmails

from .team_caching import get_team_in_cache, set_team_in_cache

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
    def get_queryset(self):
        return super().get_queryset().defer(*DEPRECATED_ATTRS)

    def set_test_account_filters(self, organization: Optional[Any]) -> List:
        filters = [
            {
                "key": "$host",
                "operator": "is_not",
                "value": ["localhost:8000", "localhost:5000", "127.0.0.1:8000", "127.0.0.1:3000", "localhost:3000"],
                "type": "event",
            }
        ]
        if organization:
            example_emails = organization.members.only("email")
            generic_emails = GenericEmails()
            example_emails = [email.email for email in example_emails if not generic_emails.is_generic(email.email)]
            if len(example_emails) > 0:
                example_email = re.search(r"@[\w.]+", example_emails[0])
                if example_email:
                    return [
                        {"key": "email", "operator": "not_icontains", "value": example_email.group(), "type": "person"}
                    ] + filters
        return filters

    def create_with_data(self, user: Any = None, default_dashboards: bool = True, **kwargs) -> "Team":
        kwargs["test_account_filters"] = self.set_test_account_filters(kwargs.get("organization"))
        team = Team.objects.create(**kwargs)

        # Create default dashboards (skipped for demo projects)
        if default_dashboards:
            dashboard = Dashboard.objects.create(name="My App Dashboard", pinned=True, team=team)
            create_dashboard_from_template("DEFAULT_APP", dashboard)
            team.primary_dashboard = dashboard
            team.save()
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

    def get_team_from_cache_or_token(self, token: Optional[str]) -> Optional["Team"]:
        if not token:
            return None
        try:
            team = get_team_in_cache(token)
            if team:
                return team

            team = Team.objects.get(api_token=token)
            set_team_in_cache(token, team)
            return team

        except Team.DoesNotExist:
            return None


def get_default_data_attributes() -> List[str]:
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
        max_length=200, default="Default Project", validators=[MinLengthValidator(1, "Project must have a name!")]
    )
    slack_incoming_webhook: models.CharField = models.CharField(max_length=500, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    anonymize_ips: models.BooleanField = models.BooleanField(default=False)
    completed_snippet_onboarding: models.BooleanField = models.BooleanField(default=False)
    ingested_event: models.BooleanField = models.BooleanField(default=False)
    session_recording_opt_in: models.BooleanField = models.BooleanField(default=False)
    capture_console_log_opt_in: models.BooleanField = models.BooleanField(null=True, blank=True)
    capture_performance_opt_in: models.BooleanField = models.BooleanField(null=True, blank=True)
    session_recording_version: models.CharField = models.CharField(null=True, blank=True, max_length=24)
    signup_token: models.CharField = models.CharField(max_length=200, null=True, blank=True)
    is_demo: models.BooleanField = models.BooleanField(default=False)
    access_control: models.BooleanField = models.BooleanField(default=False)
    # This is not a manual setting. It's updated automatically to reflect if the team uses site apps or not.
    inject_web_apps: models.BooleanField = models.BooleanField(null=True)

    test_account_filters: models.JSONField = models.JSONField(default=list)
    test_account_filters_default_checked: models.BooleanField = models.BooleanField(null=True, blank=True)

    path_cleaning_filters: models.JSONField = models.JSONField(default=list, null=True, blank=True)
    timezone: models.CharField = models.CharField(max_length=240, choices=TIMEZONES, default="UTC")
    data_attributes: models.JSONField = models.JSONField(default=get_default_data_attributes)
    person_display_name_properties: ArrayField = ArrayField(models.CharField(max_length=400), null=True, blank=True)
    live_events_columns: ArrayField = ArrayField(models.TextField(), null=True, blank=True)
    recording_domains: ArrayField = ArrayField(models.CharField(max_length=200, null=True), blank=True, null=True)

    primary_dashboard: models.ForeignKey = models.ForeignKey(
        "posthog.Dashboard", on_delete=models.SET_NULL, null=True, related_name="primary_dashboard_teams", blank=True
    )  # Dashboard shown on project homepage

    # This is meant to be used as a stopgap until https://github.com/PostHog/meta/pull/39 gets implemented
    # Switches _most_ queries to using distinct_id as aggregator instead of person_id
    @property
    def aggregate_users_by_distinct_id(self) -> bool:
        return str(self.pk) in get_list(get_instance_setting("AGGREGATE_BY_DISTINCT_IDS_TEAMS"))

    # This correlation_config is intended to be used initially for
    # `excluded_person_property_names` but will be used as a general config
    # repository for correlation related settings.
    # NOTE: we're not doing any schema checking here, just storing whatever is
    # thrown at us. Correlation code can handle schema related issues.
    correlation_config = models.JSONField(default=dict, null=True, blank=True)

    # DEPRECATED, DISUSED: recordings on CH are cleared with Clickhouse's TTL
    session_recording_retention_period_days: models.IntegerField = models.IntegerField(
        null=True, default=None, blank=True
    )
    # DEPRECATED, DISUSED: plugins are enabled for everyone now
    plugins_opt_in: models.BooleanField = models.BooleanField(default=False)
    # DEPRECATED, DISUSED: replaced with env variable OPT_OUT_CAPTURE and User.anonymized_data
    opt_out_capture: models.BooleanField = models.BooleanField(default=False)
    # DEPRECATED: in favor of `EventDefinition` model
    event_names: models.JSONField = models.JSONField(default=list, blank=True)
    event_names_with_usage: models.JSONField = models.JSONField(default=list, blank=True)
    # DEPRECATED: in favor of `PropertyDefinition` model
    event_properties: models.JSONField = models.JSONField(default=list, blank=True)
    event_properties_with_usage: models.JSONField = models.JSONField(default=list, blank=True)
    event_properties_numerical: models.JSONField = models.JSONField(default=list, blank=True)

    objects: TeamManager = TeamManager()

    @property
    def person_on_events_querying_enabled(self) -> bool:
        result = self._person_on_events_querying_enabled
        tag_queries(person_on_events_enabled=result)
        return result

    @property
    def _person_on_events_querying_enabled(self) -> bool:
        if settings.PERSON_ON_EVENTS_OVERRIDE is not None:
            return settings.PERSON_ON_EVENTS_OVERRIDE

        # on PostHog Cloud, use the feature flag
        if is_cloud():
            return posthoganalytics.feature_enabled(
                "person-on-events-enabled",
                str(self.uuid),
                groups={"organization": str(self.organization_id)},
                group_properties={
                    "organization": {"id": str(self.organization_id), "created_at": self.organization.created_at}
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )

        # If the async migration is not complete, don't enable actor on events querying.
        if not actor_on_events_ready():
            return False

        # on self-hosted, use the instance setting
        return get_instance_setting("PERSON_ON_EVENTS_ENABLED")

    @property
    def strict_caching_enabled(self) -> bool:
        enabled_teams = get_list(get_instance_setting("STRICT_CACHING_TEAMS"))
        return str(self.pk) in enabled_teams or "all" in enabled_teams

    @cached_property
    def persons_seen_so_far(self) -> int:

        from posthog.client import sync_execute
        from posthog.queries.person_query import PersonQuery

        filter = Filter(data={"full": "true"})
        person_query, person_query_params = PersonQuery(filter, self.id).get_query()

        return sync_execute(
            f"""
            SELECT count(1) FROM (
                {person_query}
            )
        """,
            {**person_query_params, **filter.hogql_context.values},
        )[0][0]

    @lru_cache(maxsize=5)
    def groups_seen_so_far(self, group_type_index: GroupTypeIndex) -> int:

        from posthog.client import sync_execute

        return sync_execute(
            f"""
            SELECT
                count(DISTINCT group_key)
            FROM groups
            WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s
        """,
            {"team_id": self.pk, "group_type_index": group_type_index},
        )[0][0]

    def __str__(self):
        if self.name:
            return self.name
        if self.app_urls and self.app_urls[0]:
            return ", ".join(self.app_urls)
        return str(self.pk)

    __repr__ = sane_repr("uuid", "name", "api_token")


@mutable_receiver(post_save, sender=Team)
def put_team_in_cache_on_save(sender, instance: Team, **kwargs):
    set_team_in_cache(instance.api_token, instance)


@mutable_receiver(post_delete, sender=Team)
def delete_team_in_cache_on_delete(sender, instance: Team, **kwargs):
    set_team_in_cache(instance.api_token, None)


def groups_on_events_querying_enabled():
    """
    Returns whether to allow querying groups columns on events.

    Remove all usages of this when the feature is released to everyone.
    """
    return actor_on_events_ready() and get_instance_setting("GROUPS_ON_EVENTS_ENABLED")


def get_available_features_for_team(team_id: int):
    available_features: Optional[List[str]] = (
        Team.objects.select_related("organization")
        .values_list("organization__available_features", flat=True)
        .get(id=team_id)
    )

    return available_features
