from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Dashboard, FeedActivityType, FeedPreferences, Team, User
from posthog.temporal.weekly_digest import queries


class FeedItemSerializer(serializers.Serializer):
    """Serializer for individual feed items"""

    id = serializers.CharField()
    type = serializers.ChoiceField(choices=FeedActivityType.choices)
    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField()
    created_at = serializers.DateTimeField()
    creator = serializers.JSONField(required=False, allow_null=True)
    url = serializers.CharField()
    can_summarize = serializers.BooleanField(default=False)


class FeedPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedPreferences
        fields = [
            "id",
            "enabled_types",
            "feed_enabled",
            "ai_summarization_enabled",
            "updated_at",
        ]


class FeedViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"

    def list(self, request: Request, *args, **kwargs) -> Response:
        """
        GET /api/environments/:team_id/feed/

        Query params:
        - type: Filter by activity type (optional)
        - date_from: ISO date string (default: 7 days ago)
        - date_to: ISO date string (default: now)
        - limit: Pagination limit (default: 20, max: 100)
        - offset: Pagination offset (default: 0)
        """
        team = self.team
        user = request.user

        # Get user preferences
        preferences = self._get_or_create_preferences(user, team)

        if not preferences.feed_enabled:
            return Response({"results": [], "count": 0, "next": None, "previous": None})

        # Parse query params
        activity_type = request.query_params.get("type")
        date_from = self._parse_date(request.query_params.get("date_from"), default=timezone.now() - timedelta(days=7))
        date_to = self._parse_date(request.query_params.get("date_to"), default=timezone.now())
        limit = min(int(request.query_params.get("limit", 20)), 100)
        offset = int(request.query_params.get("offset", 0))

        # Build feed items
        feed_items = self._build_feed_items(
            team=team,
            user=user,
            preferences=preferences,
            activity_type=activity_type,
            date_from=date_from,
            date_to=date_to,
        )

        # Paginate
        total_count = len(feed_items)
        feed_items = feed_items[offset : offset + limit]

        serializer = FeedItemSerializer(feed_items, many=True)

        return Response(
            {
                "results": serializer.data,
                "count": total_count,
                "next": offset + limit if offset + limit < total_count else None,
                "previous": offset - limit if offset >= limit else None,
            }
        )

    @action(methods=["GET", "PATCH"], detail=False, url_path="preferences")
    def preferences(self, request: Request, *args, **kwargs) -> Response:
        """
        GET/PATCH /api/environments/:team_id/feed/preferences/

        Get or update user's feed preferences for this team
        """
        preferences = self._get_or_create_preferences(request.user, self.team)

        if request.method == "GET":
            serializer = FeedPreferencesSerializer(preferences)
            return Response(serializer.data)

        elif request.method == "PATCH":
            serializer = FeedPreferencesSerializer(preferences, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

    def _get_or_create_preferences(self, user: User, team: Team) -> FeedPreferences:
        """Get or create preferences with defaults"""
        preferences, created = FeedPreferences.objects.get_or_create(
            user=user,
            team=team,
            defaults={
                "enabled_types": FeedPreferences.get_default_enabled_types(),
                "feed_enabled": True,
                "ai_summarization_enabled": True,
            },
        )
        return preferences

    def _build_feed_items(
        self,
        team: Team,
        user: User,
        preferences: FeedPreferences,
        activity_type: str | None,
        date_from: datetime,
        date_to: datetime,
    ) -> list[dict[str, Any]]:
        """Build feed items from various sources"""
        feed_items = []
        enabled_types = preferences.enabled_activity_types

        # Filter by specific type if requested
        if activity_type:
            enabled_types = [activity_type] if activity_type in enabled_types else []

        # Fetch each activity type
        if FeedActivityType.DASHBOARD in enabled_types:
            feed_items.extend(self._fetch_dashboards(team, date_from, date_to))

        if FeedActivityType.EVENT_DEFINITION in enabled_types:
            feed_items.extend(self._fetch_event_definitions(team, date_from, date_to))

        if FeedActivityType.EXPERIMENT_LAUNCHED in enabled_types:
            feed_items.extend(self._fetch_experiments_launched(team, date_from, date_to))

        if FeedActivityType.EXPERIMENT_COMPLETED in enabled_types:
            feed_items.extend(self._fetch_experiments_completed(team, date_from, date_to))

        if FeedActivityType.FEATURE_FLAG in enabled_types:
            feed_items.extend(self._fetch_feature_flags(team, date_from, date_to))

        if FeedActivityType.SURVEY in enabled_types:
            feed_items.extend(self._fetch_surveys(team, date_from, date_to))

        if FeedActivityType.REPLAY_PLAYLIST in enabled_types:
            feed_items.extend(self._fetch_replay_playlists(team, date_from, date_to))

        if FeedActivityType.EXTERNAL_DATA_SOURCE in enabled_types:
            feed_items.extend(self._fetch_external_data_sources(team, date_from, date_to))

        # Sort by created_at descending
        feed_items.sort(key=lambda x: x["created_at"], reverse=True)

        return feed_items

    def _fetch_dashboards(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch new dashboards"""
        dashboards = queries.query_new_dashboards(date_from, date_to).filter(team_id=team.id)

        items = []
        for d in dashboards:
            # Get full dashboard object for created_by
            try:
                dashboard = Dashboard.objects.select_related("created_by").get(id=d["id"])
                created_at = dashboard.created_at
                creator = (
                    {
                        "id": dashboard.created_by.id,
                        "name": dashboard.created_by.first_name or dashboard.created_by.email,
                    }
                    if dashboard.created_by
                    else None
                )
            except Dashboard.DoesNotExist:
                created_at = date_from
                creator = None

            items.append(
                {
                    "id": f"dashboard-{d['id']}",
                    "type": FeedActivityType.DASHBOARD,
                    "title": f"New dashboard: {d['name']}",
                    "description": f"{d['name']} was created",
                    "metadata": {"dashboard_id": d["id"], "dashboard_name": d["name"]},
                    "created_at": created_at,
                    "creator": creator,
                    "url": f"/project/{team.id}/dashboard/{d['id']}",
                    "can_summarize": False,
                }
            )

        return items

    def _fetch_event_definitions(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch new event definitions"""
        from posthog.models import EventDefinition

        events = queries.query_new_event_definitions(date_from, date_to).filter(team_id=team.id)

        items = []
        for e in events:
            # Get full object for created_at
            try:
                event_def = EventDefinition.objects.get(id=e["id"])
                created_at = event_def.created_at
            except EventDefinition.DoesNotExist:
                created_at = date_from

            items.append(
                {
                    "id": f"event-{e['id']}",
                    "type": FeedActivityType.EVENT_DEFINITION,
                    "title": f"New event: {e['name']}",
                    "description": f"Event definition '{e['name']}' was created",
                    "metadata": {"event_id": e["id"], "event_name": e["name"]},
                    "created_at": created_at,
                    "creator": None,
                    "url": f"/project/{team.id}/data-management/events/{e['id']}",
                    "can_summarize": False,
                }
            )

        return items

    def _fetch_experiments_launched(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch experiments launched"""
        from posthog.models import Experiment

        experiments = queries.query_experiments_launched(date_from, date_to).filter(team_id=team.id)

        items = []
        for e in experiments:
            # Get full object for created_by
            try:
                experiment = Experiment.objects.select_related("created_by").get(id=e["id"])
                creator = (
                    {
                        "id": experiment.created_by.id,
                        "name": experiment.created_by.first_name or experiment.created_by.email,
                    }
                    if experiment.created_by
                    else None
                )
            except Experiment.DoesNotExist:
                creator = None

            items.append(
                {
                    "id": f"experiment-launched-{e['id']}",
                    "type": FeedActivityType.EXPERIMENT_LAUNCHED,
                    "title": f"Experiment launched: {e['name']}",
                    "description": f"Experiment '{e['name']}' was launched",
                    "metadata": {"experiment_id": e["id"], "experiment_name": e["name"], "start_date": e["start_date"]},
                    "created_at": e["start_date"],
                    "creator": creator,
                    "url": f"/project/{team.id}/experiments/{e['id']}",
                    "can_summarize": False,
                }
            )

        return items

    def _fetch_experiments_completed(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch experiments completed"""
        from posthog.models import Experiment

        experiments = queries.query_experiments_completed(date_from, date_to).filter(team_id=team.id)

        items = []
        for e in experiments:
            # Get full object for created_by
            try:
                experiment = Experiment.objects.select_related("created_by").get(id=e["id"])
                creator = (
                    {
                        "id": experiment.created_by.id,
                        "name": experiment.created_by.first_name or experiment.created_by.email,
                    }
                    if experiment.created_by
                    else None
                )
            except Experiment.DoesNotExist:
                creator = None

            items.append(
                {
                    "id": f"experiment-completed-{e['id']}",
                    "type": FeedActivityType.EXPERIMENT_COMPLETED,
                    "title": f"Experiment completed: {e['name']}",
                    "description": f"Experiment '{e['name']}' was completed",
                    "metadata": {
                        "experiment_id": e["id"],
                        "experiment_name": e["name"],
                        "start_date": e["start_date"],
                        "end_date": e["end_date"],
                    },
                    "created_at": e["end_date"],
                    "creator": creator,
                    "url": f"/project/{team.id}/experiments/{e['id']}",
                    "can_summarize": False,
                }
            )

        return items

    def _fetch_feature_flags(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch new feature flags"""
        from posthog.models import FeatureFlag

        flags = queries.query_new_feature_flags(date_from, date_to).filter(team_id=team.id)

        items = []
        for f in flags:
            # Get full object for created_by and created_at
            try:
                flag = FeatureFlag.objects.select_related("created_by").get(id=f["id"])
                created_at = flag.created_at
                creator = (
                    {
                        "id": flag.created_by.id,
                        "name": flag.created_by.first_name or flag.created_by.email,
                    }
                    if flag.created_by
                    else None
                )
            except FeatureFlag.DoesNotExist:
                created_at = date_from
                creator = None

            items.append(
                {
                    "id": f"feature-flag-{f['id']}",
                    "type": FeedActivityType.FEATURE_FLAG,
                    "title": f"New feature flag: {f['name']}",
                    "description": f"Feature flag '{f['name']}' was created",
                    "metadata": {"flag_id": f["id"], "flag_name": f["name"], "flag_key": f["key"]},
                    "created_at": created_at,
                    "creator": creator,
                    "url": f"/project/{team.id}/feature_flags/{f['id']}",
                    "can_summarize": False,
                }
            )

        return items

    def _fetch_surveys(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch launched surveys"""
        from posthog.models import Survey

        surveys = queries.query_surveys_launched(date_from, date_to).filter(team_id=team.id)

        items = []
        for s in surveys:
            # Get full object for created_by
            try:
                survey = Survey.objects.select_related("created_by").get(id=s["id"])
                creator = (
                    {
                        "id": survey.created_by.id,
                        "name": survey.created_by.first_name or survey.created_by.email,
                    }
                    if survey.created_by
                    else None
                )
            except Survey.DoesNotExist:
                creator = None

            items.append(
                {
                    "id": f"survey-{s['id']}",
                    "type": FeedActivityType.SURVEY,
                    "title": f"Survey launched: {s['name']}",
                    "description": s.get("description", "") or f"Survey '{s['name']}' was launched",
                    "metadata": {
                        "survey_id": s["id"],
                        "survey_name": s["name"],
                        "start_date": s["start_date"],
                        "description": s.get("description"),
                    },
                    "created_at": s["start_date"],
                    "creator": creator,
                    "url": f"/project/{team.id}/surveys/{s['id']}",
                    "can_summarize": False,
                }
            )

        return items

    def _fetch_replay_playlists(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch popular replay playlists"""
        from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

        playlists = queries.query_saved_filters(date_from, date_to).filter(team_id=team.id)

        items = []
        for p in playlists:
            # Get full object for created_at and created_by
            try:
                playlist = SessionRecordingPlaylist.objects.select_related("created_by").get(short_id=p["short_id"])
                created_at = playlist.created_at
                creator = (
                    {
                        "id": playlist.created_by.id,
                        "name": playlist.created_by.first_name or playlist.created_by.email,
                    }
                    if playlist.created_by
                    else None
                )
            except SessionRecordingPlaylist.DoesNotExist:
                created_at = date_from
                creator = None

            items.append(
                {
                    "id": f"playlist-{p['short_id']}",
                    "type": FeedActivityType.REPLAY_PLAYLIST,
                    "title": p["name"] or "Untitled playlist",
                    "description": f"{p['view_count']} views",
                    "metadata": {
                        "short_id": p["short_id"],
                        "name": p["name"],
                        "view_count": p["view_count"],
                    },
                    "created_at": created_at,
                    "creator": creator,
                    "url": f"/project/{team.id}/replay/playlists/{p['short_id']}",
                    "can_summarize": True,  # Replay playlists can be summarized
                }
            )

        return items

    def _fetch_external_data_sources(self, team: Team, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        """Fetch new external data sources"""
        from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

        sources = queries.query_new_external_data_sources(date_from, date_to).filter(team_id=team.id)

        items = []
        for s in sources:
            # Get full object for created_at and created_by
            try:
                source = ExternalDataSource.objects.select_related("created_by").get(id=s["id"])
                created_at = source.created_at
                creator = (
                    {
                        "id": source.created_by.id,
                        "name": source.created_by.first_name or source.created_by.email,
                    }
                    if source.created_by
                    else None
                )
            except ExternalDataSource.DoesNotExist:
                created_at = date_from
                creator = None

            items.append(
                {
                    "id": f"data-source-{s['id']}",
                    "type": FeedActivityType.EXTERNAL_DATA_SOURCE,
                    "title": f"New data connection: {s['source_type']}",
                    "description": f"External data source of type '{s['source_type']}' was connected",
                    "metadata": {"source_id": s["id"], "source_type": s["source_type"]},
                    "created_at": created_at,
                    "creator": creator,
                    "url": f"/project/{team.id}/data-warehouse",
                    "can_summarize": False,
                }
            )

        return items

    def _parse_date(self, date_str: str | None, default: datetime) -> datetime:
        """Parse ISO date string or return default"""
        if not date_str:
            return default
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return default
