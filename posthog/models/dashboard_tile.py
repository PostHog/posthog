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


class DashboardWidget(models.Model):
    class WidgetType(models.TextChoices):
        EXPERIMENT = "experiment", "Experiment"
        LOGS = "logs", "Logs"
        ERROR_TRACKING = "error_tracking", "Error tracking"
        SESSION_REPLAYS = "session_replays", "Session replays"
        SURVEY_RESPONSES = "survey_responses", "Survey responses"

    widget_type = models.CharField(max_length=40, choices=WidgetType.choices)
    config = models.JSONField(default=dict)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_dashboard_widgets",
    )


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
    widget = models.ForeignKey(
        "posthog.DashboardWidget",
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
    show_description = models.BooleanField(null=True, blank=True)

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
            UniqueConstraint(
                fields=["dashboard", "widget"],
                name="unique_dashboard_widget",
                condition=Q(("widget__isnull", False)),
            ),
            models.CheckConstraint(
                check=build_unique_relationship_check(("insight", "text", "widget")),
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

        related_fields = sum(map(bool, [getattr(self, o_field) for o_field in ("insight", "text", "widget")]))
        if related_fields != 1:
            raise ValidationError("Can only set exactly one of insight, text, or widget for this tile")

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
            widget=self.widget,
            color=self.color,
            layouts=self.layouts,
            show_description=self.show_description,
        )

    @staticmethod
    def sort_tiles_by_layout(
        tiles: list["DashboardTile"] | QuerySet["DashboardTile"], layout_size: str = "sm"
    ) -> list["DashboardTile"]:
        """Sort tiles by their layout position (y, then x)."""
        return sorted(
            tiles,
            key=lambda tile: (
                tile.layouts.get(layout_size, {}).get("y", 100),
                tile.layouts.get(layout_size, {}).get("x", 100),
            ),
        )

    @staticmethod
    def dashboard_queryset(queryset: QuerySet) -> QuerySet:
        return (
            queryset.select_related(
                "insight",
                "text",
                "widget",
                "insight__created_by",
                "insight__last_modified_by",
                "insight__team",
            )
            .exclude(dashboard__deleted=True, deleted=True)
            .filter(Q(insight__deleted=False) | Q(insight__isnull=True))
            .order_by("insight__order")
        )
