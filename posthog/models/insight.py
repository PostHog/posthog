import secrets
import string
from typing import Optional

from django.contrib.postgres.fields.array import ArrayField
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from django_deprecate_fields import deprecate_field

from posthog.models.dashboard import Dashboard
from posthog.models.filters.utils import get_filter
from posthog.utils import generate_cache_key


def generate_short_id():
    """Generate securely random 8 characters long alphanumeric ID."""
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))


class Insight(models.Model):
    """
    Stores saved insights along with their entire configuration options. Saved insights can be stored as standalone
    reports or part of a dashboard.
    """

    dashboard: models.ForeignKey = models.ForeignKey(
        "Dashboard", related_name="items", on_delete=models.CASCADE, null=True, blank=True,
    )
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    derived_name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    filters: models.JSONField = models.JSONField(default=dict)
    filters_hash: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    order: models.IntegerField = models.IntegerField(null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    saved: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(null=True, blank=True, auto_now_add=True)
    layouts: models.JSONField = models.JSONField(default=dict)
    color: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    last_refresh: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    refreshing: models.BooleanField = models.BooleanField(default=False)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    # Indicates if it's a sample graph generated by dashboard templates
    is_sample: models.BooleanField = models.BooleanField(default=False)
    # Unique ID per team for easy sharing and short links
    short_id: models.CharField = models.CharField(
        max_length=12, blank=True, default=generate_short_id,
    )
    favorited: models.BooleanField = models.BooleanField(default=False)
    refresh_attempt: models.IntegerField = models.IntegerField(null=True, blank=True)
    last_modified_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_modified_by: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="modified_insights",
    )

    # TODO: dive dashboards have never been shipped, but they still may be in the future
    dive_dashboard: models.ForeignKey = models.ForeignKey("Dashboard", on_delete=models.SET_NULL, null=True, blank=True)
    # DEPRECATED: in practically all cases field `last_modified_at` should be used instead
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    # DEPRECATED: use `display` property of the Filter object instead
    type: models.CharField = deprecate_field(models.CharField(max_length=400, null=True, blank=True))
    # DEPRECATED: we don't store funnels as a separate model any more
    funnel: models.IntegerField = deprecate_field(models.IntegerField(null=True, blank=True))

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), blank=True, default=list), return_instead=[],
    )
    tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), blank=True, default=None), return_instead=[],
    )

    # Changing these fields materially alters the Insight, so these count for the "last_modified_*" fields
    MATERIAL_INSIGHT_FIELDS = {"name", "description", "filters"}

    class Meta:
        db_table = "posthog_dashboarditem"
        unique_together = (
            "team",
            "short_id",
        )

    def dashboard_filters(self, dashboard: Optional[Dashboard] = None):
        if dashboard is None:
            dashboard = self.dashboard
        if dashboard:
            return {**self.filters, **dashboard.filters}
        else:
            return self.filters

    @property
    def effective_restriction_level(self) -> Dashboard.RestrictionLevel:
        return (
            self.dashboard.effective_restriction_level
            if self.dashboard is not None
            else Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def get_effective_privilege_level(self, user_id: int) -> Dashboard.PrivilegeLevel:
        return (
            self.dashboard.get_effective_privilege_level(user_id)
            if self.dashboard is not None
            else Dashboard.PrivilegeLevel.CAN_EDIT
        )


@receiver(pre_save, sender=Dashboard)
def dashboard_saved(sender, instance: Dashboard, **kwargs):
    for item in instance.items.all():
        dashboard_item_saved(sender, item, dashboard=instance, **kwargs)
        item.save()


@receiver(pre_save, sender=Insight)
def dashboard_item_saved(sender, instance: Insight, dashboard=None, **kwargs):
    if instance.filters and instance.filters != {}:
        filter = get_filter(data=instance.dashboard_filters(dashboard=dashboard), team=instance.team)

        instance.filters_hash = generate_cache_key("{}_{}".format(filter.toJSON(), instance.team_id))


class InsightViewed(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user", "insight"], name="posthog_unique_insightviewed"),
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    insight: models.ForeignKey = models.ForeignKey(Insight, on_delete=models.CASCADE)
    last_viewed_at: models.DateTimeField = models.DateTimeField()
