from typing import Any, Dict, List

from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_deprecate_fields import deprecate_field

from posthog.models.tagged_item import EnterpriseTaggedItem


class Dashboard(models.Model):
    CREATION_MODE_CHOICES = (
        ("default", "Default"),
        ("template", "Template"),  # dashboard was created from a predefined template
        ("duplicate", "Duplicate"),  # dashboard was duplicated from another dashboard
    )

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.TextField = models.TextField(blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    pinned: models.BooleanField = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    share_token: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    is_shared: models.BooleanField = models.BooleanField(default=False)
    last_accessed_at: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    filters: models.JSONField = models.JSONField(default=dict)
    creation_mode: models.CharField = models.CharField(max_length=16, default="default", choices=CREATION_MODE_CHOICES)

    global_tags: GenericRelation = GenericRelation(EnterpriseTaggedItem, related_query_name="dashboard")

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), blank=True, default=list), return_instead=[]
    )

    def get_analytics_metadata(self) -> Dict[str, Any]:
        """
        Returns serialized information about the object for analytics reporting.
        """
        return {
            "pinned": self.pinned,
            "item_count": self.items.count(),
            "is_shared": self.is_shared,
            "created_at": self.created_at,
            "has_description": self.description != "",
            "tags_count": len(self.tags),
        }
