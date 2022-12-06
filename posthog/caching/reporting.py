import dataclasses
from typing import Optional, Union

import structlog
from django.db.models.expressions import F
from django.db.models.query import QuerySet
from django.utils import timezone
from sentry_sdk import capture_exception, push_scope
from statshog.defaults.django import statsd

from posthog.models import DashboardTile, Insight, Team

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class CacheUpdateReporting:
    dashboard_id: Optional[int]
    dashboard_tiles_queryset: QuerySet
    insight_id: Union[int, str]
    insights_queryset: QuerySet
    key: str
    team: Team

    def on_results(self, stat: str) -> None:
        self.insights_queryset.update(last_refresh=timezone.now(), refreshing=False, refresh_attempt=0)
        self.dashboard_tiles_queryset.update(last_refresh=timezone.now(), refreshing=False, refresh_attempt=0)
        statsd.incr(stat, tags={"team": self.team.id})

    def on_query_error(
        self,
        e: Exception,
    ) -> None:
        statsd.incr("update_cache_item_error", tags={"team": self.team.id})
        self.mark_refresh_attempt_for(self.insights_queryset)
        self.mark_refresh_attempt_for(self.dashboard_tiles_queryset)
        with push_scope() as scope:
            scope.set_tag("cache_key", self.key)
            scope.set_tag("team_id", self.team.id)
            scope.set_tag("insight_id", self.insight_id)
            scope.set_tag("dashboard_id", self.dashboard_id)
            capture_exception(e)
        logger.error("update_cache_item_error", exc=e, exc_info=True, team_id=self.team.id, cache_key=self.key)

    def on_no_results(self) -> None:
        self.insights_queryset.update(last_refresh=timezone.now(), refreshing=False)
        self.dashboard_tiles_queryset.update(last_refresh=timezone.now(), refreshing=False)
        statsd.incr(
            "update_cache_item_no_results",
            tags={
                "team": self.team.id,
                "cache_key": self.key,
                "insight_id": self.insight_id,
                "dashboard_id": self.dashboard_id,
            },
        )
        self.mark_refresh_attempt_when_no_results()

    def mark_refresh_attempt_when_no_results(self) -> None:
        if self.insights_queryset.exists() or self.dashboard_tiles_queryset.exists():
            self.mark_refresh_attempt_for(self.insights_queryset)
            self.mark_refresh_attempt_for(self.dashboard_tiles_queryset)
        else:
            if self.insight_id != "unknown":
                self.mark_refresh_attempt_for(
                    Insight.objects.filter(id=self.insight_id)
                    if not self.dashboard_id
                    else DashboardTile.objects.filter(insight_id=self.insight_id, dashboard_id=self.dashboard_id)
                )

    @staticmethod
    def mark_refresh_attempt_for(queryset: QuerySet) -> None:
        queryset.filter(refresh_attempt=None).update(refresh_attempt=0)
        queryset.update(refreshing=False, refresh_attempt=F("refresh_attempt") + 1)
