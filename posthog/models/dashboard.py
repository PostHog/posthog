from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import sane_repr

from posthog.utils import absolute_uri


class DashboardManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)


class Dashboard(models.Model):
    class CreationMode(models.TextChoices):
        DEFAULT = "default", "Default"
        TEMPLATE = (
            "template",
            "Template",
        )  # dashboard was created from a predefined template
        DUPLICATE = (
            "duplicate",
            "Duplicate",
        )  # dashboard was duplicated from another dashboard

    class RestrictionLevel(models.IntegerChoices):
        """Collaboration restriction level (which is a dashboard setting). Sync with PrivilegeLevel."""

        EVERYONE_IN_PROJECT_CAN_EDIT = 21, "Everyone in the project can edit"
        ONLY_COLLABORATORS_CAN_EDIT = (
            37,
            "Only those invited to this dashboard can edit",
        )

    class PrivilegeLevel(models.IntegerChoices):
        """Collaboration privilege level (which is a user property). Sync with RestrictionLevel."""

        CAN_VIEW = 21, "Can view dashboard"
        CAN_EDIT = 37, "Can edit dashboard"

    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    last_accessed_at = models.DateTimeField(blank=True, null=True)
    filters = models.JSONField(default=dict)
    creation_mode = models.CharField(max_length=16, default="default", choices=CreationMode.choices)
    restriction_level = models.PositiveSmallIntegerField(
        default=RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        choices=RestrictionLevel.choices,
    )
    insights = models.ManyToManyField(
        "posthog.Insight",
        related_name="dashboards",
        through="DashboardTile",
        blank=True,
    )

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
    deprecated_tags_v2: ArrayField = ArrayField(
        models.CharField(max_length=32),
        null=True,
        blank=True,
        default=None,
        db_column="tags",
    )

    # DEPRECATED: using the new "sharing" relation instead
    share_token = models.CharField(max_length=400, null=True, blank=True)
    # DEPRECATED: using the new "is_sharing_enabled" relation instead
    is_shared = models.BooleanField(default=False)

    objects = DashboardManager()
    objects_including_soft_deleted = models.Manager()

    __repr__ = sane_repr("team_id", "id", "name")

    class Meta:
        indexes = [
            models.Index(
                name="idx_dashboard_deleted_team_id",
                fields=["-pinned", "name", "deleted", "team_id"],
                condition=models.Q(deleted=False),
            ),
        ]

    def __str__(self):
        return self.name or str(self.id)

    @property
    def is_sharing_enabled(self):
        # uses .all and not .first so that prefetching in serializers can be used
        sharing_configurations = self.sharingconfiguration_set.all()
        return sharing_configurations[0].enabled if sharing_configurations and sharing_configurations[0] else False

    @property
    def url(self):
        return absolute_uri(f"/dashboard/{self.id}")

    def get_analytics_metadata(self) -> dict[str, Any]:
        """
        Returns serialized information about the object for analytics reporting.
        """
        return {
            "pinned": self.pinned,
            "item_count": self.tiles.exclude(insight=None).count(),
            "is_shared": self.is_sharing_enabled,
            "created_at": self.created_at,
            "has_description": self.description != "",
            "tags_count": self.tagged_items.count(),
        }
