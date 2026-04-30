from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, QuerySet, UniqueConstraint
from django.utils import timezone

from posthog.models.utils import UUIDModel, build_unique_relationship_check

from products.dashboards.backend.models.dashboard import Dashboard


class Text(models.Model):
    body = models.CharField(max_length=4000, null=True, blank=True)

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_text_tiles",
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    class Meta:
        db_table = "posthog_text"


class ButtonTile(UUIDModel):
    url = models.CharField(max_length=2000)
    text = models.CharField(max_length=200)
    placement = models.CharField(max_length=10, choices=[("left", "Left"), ("right", "Right")], default="left")
    style = models.CharField(
        max_length=10, choices=[("primary", "Primary"), ("secondary", "Secondary")], default="primary"
    )

    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    last_modified_at = models.DateTimeField(default=timezone.now)
    last_modified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_button_tiles",
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    class Meta:
        db_table = "posthog_buttontile"


class DashboardTileManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True).exclude(dashboard__deleted=True)


class DashboardTile(models.Model):
    # Relations
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE, related_name="tiles")
    insight = models.ForeignKey(
        "posthog.Insight",
        on_delete=models.CASCADE,
        related_name="dashboard_tiles",
        null=True,
    )
    text = models.ForeignKey(
        "dashboards.Text",
        on_delete=models.CASCADE,
        related_name="dashboard_tiles",
        null=True,
    )
    button_tile = models.ForeignKey(
        "dashboards.ButtonTile",
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

    transparent_background = models.BooleanField(null=True, blank=True)

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
                fields=["dashboard", "button_tile"],
                name="unique_dashboard_button_tile",
                condition=Q(("button_tile__isnull", False)),
            ),
            models.CheckConstraint(
                condition=build_unique_relationship_check(("insight", "text", "button_tile")),
                name="dash_tile_exactly_one_related_object",
            ),
        ]
        db_table = "posthog_dashboardtile"

    def save(self, *args, **kwargs) -> None:
        if self.insight is not None:
            has_no_filters_hash = self.filters_hash is None
            if has_no_filters_hash and self.insight.filters != {}:
                from posthog.models.insight import generate_insight_filters_hash

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

        related_fields = sum(map(bool, [getattr(self, o_field) for o_field in ("insight", "text", "button_tile")]))
        if related_fields != 1:
            raise ValidationError("Can only set exactly one of insight, text, or button_tile for this tile")

        if self.insight is None and (
            self.filters_hash is not None
            or self.refreshing is not None
            or self.refresh_attempt is not None
            or self.last_refresh is not None
        ):
            raise ValidationError("Fields to do with refreshing are only applicable when this is an insight tile")

    def prepare_move_to_dashboard(self, to_dashboard_id: int) -> None:
        """Remove other tile rows on the destination that reference the same insight/text/button.

        A soft-deleted row still occupies the unique (dashboard, insight|text|button) key; delete it so
        ``dashboard_id`` can be updated onto this tile. If a non-deleted row exists, moving is invalid.
        """
        if self.insight is not None:
            qs = DashboardTile.objects_including_soft_deleted.filter(
                dashboard_id=to_dashboard_id, insight=self.insight
            ).exclude(pk=self.pk)
        elif self.text is not None:
            qs = DashboardTile.objects_including_soft_deleted.filter(
                dashboard_id=to_dashboard_id, text=self.text
            ).exclude(pk=self.pk)
        elif self.button_tile is not None:
            qs = DashboardTile.objects_including_soft_deleted.filter(
                dashboard_id=to_dashboard_id, button_tile=self.button_tile
            ).exclude(pk=self.pk)
        else:
            return
        for stale in qs:
            if stale.deleted is not True:
                raise ValidationError("This content is already on the destination dashboard.")
            stale.delete()

    def copy_to_dashboard(self, dashboard: Dashboard) -> None:
        """
        Place this tile's content on another dashboard: create a new row, or undelete a soft-deleted
        row for the same insight, text, or button (unique constraint would block a second insert otherwise).

        The ``copy_tile`` API still only exposes insight and text tiles; dashboard duplication uses this
        method for all tile types including buttons.
        """
        if self.insight is not None:
            existing = DashboardTile.objects_including_soft_deleted.filter(
                dashboard=dashboard, insight=self.insight
            ).first()
        elif self.text is not None:
            existing = DashboardTile.objects_including_soft_deleted.filter(dashboard=dashboard, text=self.text).first()
        elif self.button_tile is not None:
            existing = DashboardTile.objects_including_soft_deleted.filter(
                dashboard=dashboard, button_tile=self.button_tile
            ).first()
        else:
            raise ValidationError("Cannot copy tile without insight, text, or button_tile.")

        if existing:
            if existing.deleted is not True:
                raise ValidationError("Tile already exists on destination dashboard")
            existing.deleted = False
            existing.layouts = self.layouts
            existing.color = self.color
            existing.show_description = self.show_description
            existing.transparent_background = self.transparent_background
            existing.filters_overrides = self.filters_overrides
            existing.save()
            return

        DashboardTile.objects.create(
            dashboard=dashboard,
            insight=self.insight,
            text=self.text,
            button_tile=self.button_tile,
            color=self.color,
            layouts=self.layouts,
            show_description=self.show_description,
            transparent_background=self.transparent_background,
            filters_overrides=self.filters_overrides,
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
                "button_tile",
                "insight__created_by",
                "insight__last_modified_by",
                "insight__team",
            )
            .prefetch_related("text__dashboard_tiles", "button_tile__dashboard_tiles")
            .exclude(dashboard__deleted=True, deleted=True)
            .filter(Q(insight__deleted=False) | Q(insight__isnull=True))
            .order_by("insight__order")
        )
