from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FeatureRequestStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    PLANNED = "planned", "Planned"
    COMPLETED = "completed", "Completed"
    WONT_FIX = "wont_fix", "Won't fix"
    DUPLICATE = "duplicate", "Duplicate"


class FeatureRequestPriority(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class FeatureRequestHistorySource(models.TextChoices):
    MANUAL = "manual", "Manual"


class FeatureRequestProductArea(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    name = models.CharField(max_length=200)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    updated_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"),
                models.F("team"),
                name="unique_feature_request_area_name_per_team",
            ),
        ]
        ordering = ["display_order", "name", "id"]


class FeatureRequest(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    title = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=FeatureRequestStatus.choices,
        default=FeatureRequestStatus.REQUESTED,
    )
    priority = models.CharField(max_length=16, choices=FeatureRequestPriority.choices, null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by_id = models.BigIntegerField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1, db_default=1)
    idempotency_key = models.UUIDField(null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    updated_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    product_areas: models.ManyToManyField = models.ManyToManyField(
        FeatureRequestProductArea,
        through="FeatureRequestProductAreaLink",
        related_name="feature_requests",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "idempotency_key"],
                condition=Q(idempotency_key__isnull=False),
                name="unique_feature_request_idempotency_key_per_team",
            ),
        ]
        ordering = ["-updated_at", "-created_at", "-id"]


class FeatureRequestHistory(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.CASCADE,
        related_name="history",
    )
    changes = models.JSONField(default=list)
    is_initial = models.BooleanField(default=False)
    source = models.CharField(
        max_length=32,
        choices=FeatureRequestHistorySource.choices,
        default=FeatureRequestHistorySource.MANUAL,
    )
    actor_id = models.BigIntegerField(null=True, blank=True)
    changed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "feature_request"],
                condition=Q(is_initial=True),
                name="unique_feature_request_initial_history",
            ),
        ]
        ordering = ["-changed_at", "-id"]


class FeatureRequestAccountLink(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.CASCADE,
        related_name="account_links",
    )
    account = models.ForeignKey(
        "customer_analytics.Account",
        on_delete=models.CASCADE,
        related_name="feature_request_links",
    )
    unlinked_at = models.DateTimeField(null=True, blank=True)
    unlinked_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "feature_request", "account"],
                name="unique_feature_request_account_link",
            ),
        ]


class FeatureRequestEvidence(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    account_link = models.ForeignKey(
        FeatureRequestAccountLink,
        on_delete=models.CASCADE,
        related_name="evidence",
    )
    summary = models.TextField(blank=True, default="")
    customer_quote = models.TextField(blank=True, default="")
    source = models.CharField(max_length=200)
    source_url = models.URLField(max_length=2000, blank=True, default="")
    requested_on = models.DateField(null=True, blank=True)
    image_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [models.F("requested_on").desc(nulls_last=True), "-created_at", "-id"]


class FeatureRequestProductAreaLink(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.CASCADE,
        related_name="product_area_links",
    )
    product_area = models.ForeignKey(
        FeatureRequestProductArea,
        on_delete=models.PROTECT,
        related_name="request_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "feature_request", "product_area"],
                name="unique_feature_request_product_area_link",
            ),
        ]
