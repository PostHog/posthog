from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, QuerySet, UniqueConstraint
from django.utils import timezone

from posthog.models.dashboard import Dashboard
from posthog.models.insight import generate_insight_filters_hash
from posthog.models.utils import build_unique_relationship_check


class Text(models.Model):
    body = models.CharField(max_length=4000, null=True, blank=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_text_tiles",
    )

    team = models.ForeignKey("Team", on_delete=models.CASCADE)


class DashboardTileManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True).exclude(dashboard__deleted=True)


class DashboardTile(models.Model):
    # Relations
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, related_name="tiles")
    insight = models.ForeignKey(
        "posthog.Insight",
        on_delete=models.CASCADE,
        related_name="dashboard_tiles",
        null=True,
    )
    text = models.ForeignKey(
        "posthog.Text",
        on_delete=models.CASCADE,
        related_name="dashboard_tiles",
        null=True,
    )

    # Tile layout and style
    layouts = models.JSONField(default=dict)
    color = models.CharField(max_length=400, null=True, blank=True)

    # caching for this dashboard & insight filter combination
    filters_hash = models.CharField(max_length=400, null=True, blank=True)
    last_refresh = models.DateTimeField(blank=True, null=True)
    refreshing = models.BooleanField(null=True)
    refresh_attempt = models.IntegerField(null=True, blank=True)
    filters_overrides = models.JSONField(default=dict, null=True, blank=True)

    deleted = models.BooleanField(null=True, blank=True)

    objects = DashboardTileManager()
    objects_including_soft_deleted: models.Manager["DashboardTile"] = models.Manager()

    class Meta:
        indexes = [models.Index(fields=["filters_hash"], name="query_by_filters_hash_idx")]
        constraints = [
            UniqueConstraint(
                fields=["dashboard", "insight"],
                name=f"unique_dashboard_insight",
                condition=Q(("insight__isnull", False)),
            ),
            UniqueConstraint(
                fields=["dashboard", "text"],
                name=f"unique_dashboard_text",
                condition=Q(("text__isnull", False)),
            ),
            models.CheckConstraint(
                check=build_unique_relationship_check(("insight", "text")),
                name="dash_tile_exactly_one_related_object",
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.insight is not None:
            has_no_filters_hash = self.filters_hash is None
            if has_no_filters_hash and self.insight.filters != {}:
                self.filters_hash = generate_insight_filters_hash(self.insight, self.dashboard)

                if "update_fields" in kwargs:
                    kwargs["update_fields"].append("filters_hash")

        super().save(*args, **kwargs)

    @property
    def caching_state(self):
        # uses .all and not .first so that prefetching can be used
        for state in self.caching_states.all():
            return state
        return None

    def clean(self):
        super().clean()

        related_fields = sum(map(bool, [getattr(self, o_field) for o_field in ("insight", "text")]))
        if related_fields != 1:
            raise ValidationError("Can only set either an insight or a text for this tile")

        if self.insight is None and (
            self.filters_hash is not None
            or self.refreshing is not None
            or self.refresh_attempt is not None
            or self.last_refresh is not None
        ):
            raise ValidationError("Fields to do with refreshing are only applicable when this is an insight tile")

    def copy_to_dashboard(self, dashboard: Dashboard) -> None:
        DashboardTile.objects.create(
            dashboard=dashboard,
            insight=self.insight,
            text=self.text,
            color=self.color,
            layouts=self.layouts,
        )

    @staticmethod
    def dashboard_queryset(queryset: QuerySet) -> QuerySet:
        return (
            queryset.select_related(
                "insight",
                "text",
                "insight__created_by",
                "insight__last_modified_by",
                "insight__team",
            )
            .exclude(dashboard__deleted=True, deleted=True)
            .filter(Q(insight__deleted=False) | Q(insight__isnull=True))
            .order_by("insight__order")
        )
